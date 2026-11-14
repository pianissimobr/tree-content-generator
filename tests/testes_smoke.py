#!/usr/bin/env python3
"""Testes de fumaça do Tree Content Generator.

Roda uma série de checagens rápidas que criam arquivos temporários em
/tmp, executam funções do gerador e validam o resultado. Se tudo passar,
retorna 0; se algo falhar, retorna 1 e lista os testes que quebraram.

Uso:
    python3 -m tests.testes_smoke

    # Ou, do diretório raiz, com cor:
    make test

Os testes cobrem:
  • Detecção de formato por magic bytes (zip, gzip, tar, tgz, android-boot)
  • Handlers nativos (ZipHandler, TarHandler) — listar e ler
  • Registry.escolher — escolha do handler correto
  • MBR falso (55 AA em offset 510) — reconhecido como disco
  • Symlink circular — não trava a geração
  • escape_md — escapa caracteres especiais de Markdown
  • valid_options — rejeita entradas fora da lista
  • generate_tree_with_content — modos inline e separate
"""

import builtins
import importlib.util
import io
import os
import shutil
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


# ============================================================
# LOCALIZAÇÃO E CARREGAMENTO DO GERADOR
# ============================================================

# A pasta tests/ fica dentro de tree-content-generator/. O gerador está
# no diretório pai desta pasta.
RAIZ = Path(__file__).resolve().parent.parent
GERADOR = RAIZ / "geradordepastasearquivos.py"


def _cores():
    """Devolve códigos ANSI se estivermos num terminal, senão vazios."""
    if sys.stdout.isatty():
        return {
            "ok": "\033[92m",
            "er": "\033[91m",
            "bo": "\033[1m",
            "av": "\033[93m",
            "end": "\033[0m",
        }
    return {"ok": "", "er": "", "bo": "", "av": "", "end": ""}


def _carregar_gerador():
    """Carrega o gerador como módulo. Sai com código 2 se não achar."""
    if not GERADOR.exists():
        print(f"ERRO: {GERADOR} não encontrado.")
        print("Você está rodando do diretório raiz do projeto?")
        sys.exit(2)
    spec = importlib.util.spec_from_file_location("tcg", GERADOR)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ============================================================
# HELPERS — criação de arquivos de teste
# ============================================================

def _criar_zip(tmp, nome="teste.zip"):
    p = tmp / nome
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("hello.txt", "olá mundo")
        z.writestr("sub/dentro.txt", "linha 1\nlinha 2\n")
    return p


def _criar_tar(tmp, nome="teste.tar"):
    p = tmp / nome
    with tarfile.open(p, "w") as t:
        dados = b"conteudo do tar"
        info = tarfile.TarInfo("dentro.txt")
        info.size = len(dados)
        t.addfile(info, io.BytesIO(dados))
    return p


def _criar_tgz(tmp, nome="teste.tgz"):
    p = tmp / nome
    with tarfile.open(p, "w:gz") as t:
        dados = b"conteudo do tgz"
        info = tarfile.TarInfo("dentro.txt")
        info.size = len(dados)
        t.addfile(info, io.BytesIO(dados))
    return p


def _criar_android_boot(tmp, nome="boot.bin"):
    p = tmp / nome
    p.write_bytes(b"ANDROID!" + b"\x00" * 200)
    return p


def _criar_mbr_falso(tmp, nome="disco.img"):
    p = tmp / nome
    buf = bytearray(1024)
    buf[510] = 0x55
    buf[511] = 0xAA
    p.write_bytes(bytes(buf))
    return p


class _FakeInput:
    """Substitui input() para testes. Devolve valores em ordem."""
    def __init__(self, respostas):
        self._it = iter(respostas)

    def __call__(self, *_a, **_k):
        try:
            return next(self._it)
        except StopIteration:
            raise EOFError


# ============================================================
# TESTES
# ============================================================
# Cada teste recebe (mod, tmp) e levanta AssertionError se falhar.
# O runner captura a exceção e reporta.

def t_detectar_zip(mod, tmp):
    """Magic de zip é reconhecido."""
    p = _criar_zip(tmp)
    assert mod.detectar_formato_por_magic(str(p)) == "zip"


def t_detectar_gzip(mod, tmp):
    """Magic de gzip é reconhecido."""
    import gzip
    p = tmp / "teste.gz"
    with gzip.open(p, "wb") as f:
        f.write(b"conteudo gzip")
    assert mod.detectar_formato_por_magic(str(p)) == "gzip"


def t_detectar_tar(mod, tmp):
    """Magic de tar é reconhecido (ustar em offset 257)."""
    p = _criar_tar(tmp)
    assert mod.detectar_formato_por_magic(str(p)) == "tar"


def t_detectar_tgz_como_gzip(mod, tmp):
    """Um .tgz tem magic de gzip (a camada externa)."""
    p = _criar_tgz(tmp)
    assert mod.detectar_formato_por_magic(str(p)) == "gzip"


def t_detectar_android_boot(mod, tmp):
    """Magic 'ANDROID!' é reconhecido."""
    p = _criar_android_boot(tmp)
    assert mod.detectar_formato_por_magic(str(p)) == "android-boot"


def t_zip_handler_listar(mod, tmp):
    """ZipHandler.listar vê as entradas certas."""
    p = _criar_zip(tmp)
    h = mod.ZipHandler()
    entradas = h.listar(str(p))
    nomes = [e[0] for e in entradas]
    assert "hello.txt" in nomes, f"hello.txt não encontrado em {nomes}"
    assert "sub/dentro.txt" in nomes, f"sub/dentro.txt não encontrado em {nomes}"


def t_zip_handler_ler(mod, tmp):
    """ZipHandler.ler devolve os bytes corretos."""
    p = _criar_zip(tmp)
    h = mod.ZipHandler()
    dados = h.ler(str(p), "hello.txt")
    assert dados == "olá mundo".encode("utf-8"), f"bytes inesperados: {dados!r}"


def t_tar_handler_listar(mod, tmp):
    """TarHandler.listar vê as entradas certas."""
    p = _criar_tar(tmp)
    h = mod.TarHandler()
    entradas = h.listar(str(p))
    nomes = [e[0] for e in entradas]
    assert "dentro.txt" in nomes, f"dentro.txt não encontrado em {nomes}"


def t_registry_escolhe_zip(mod, tmp):
    """Registry.escolher escolhe ZipHandler para um zip."""
    p = _criar_zip(tmp)
    h = mod.REGISTRY.escolher(str(p))
    assert h is not None, "Registry devolveu None para zip"
    assert h.nome == "zip", f"esperado 'zip', veio '{h.nome}'"


def t_registry_escolhe_tar(mod, tmp):
    """Registry.escolher escolhe TarHandler para um tar."""
    p = _criar_tar(tmp)
    h = mod.REGISTRY.escolher(str(p))
    assert h is not None, "Registry devolveu None para tar"
    assert h.nome == "tar", f"esperado 'tar', veio '{h.nome}'"


def t_registry_reconhece_mbr(mod, tmp):
    """MBR falso (55 AA em 510) é reconhecido como disco."""
    p = _criar_mbr_falso(tmp)
    h = mod.REGISTRY.escolher(str(p), "disco.img")
    assert h is not None, "Registry devolveu None para MBR falso"
    assert h.nome == "disk", f"esperado 'disk', veio '{h.nome}'"


def t_symlink_circular(mod, tmp):
    """Symlink circular não trava a geração da árvore."""
    loop_dir = tmp / "loopdir"
    loop_dir.mkdir()
    (loop_dir / "self").symlink_to(loop_dir, target_is_directory=True)

    out = tmp / "saida.md"
    ok = mod.generate_tree_only(str(loop_dir), str(out))
    assert ok is True, "generate_tree_only retornou False"

    texto = out.read_text(encoding="utf-8")
    # O conteúdo deve mencionar 'circular' em algum ponto (link não expandido)
    assert "circular" in texto.lower(), (
        "saída não menciona 'circular'; pode não ter detectado o loop"
    )


def t_escape_md(mod, tmp):
    """escape_md escapa asteriscos, underlines e afins."""
    r = mod.escape_md("a*b_c")
    assert r == "a\\*b\\_c", f"esperado 'a\\*b\\_c', veio {r!r}"

    # Colchetes também
    r2 = mod.escape_md("nome[1].py")
    assert "\\[" in r2 and "\\]" in r2, f"colchetes não escapados: {r2!r}"


def t_valid_options_estrito(mod, tmp):
    """get_input rejeita entrada fora de valid_options."""
    orig = builtins.input
    try:
        # Primeira resposta é "9" (inválida), depois "2" (válida)
        builtins.input = _FakeInput(["9", "2"])
        r = mod.get_input("?", default="1", valid_options=["1", "2"])
        assert r == "2", f"esperado '2', veio {r!r}"
    finally:
        builtins.input = orig


def t_generate_inline(mod, tmp):
    """generate_tree_with_content em modo inline gera um .md com os arquivos."""
    d = tmp / "dir_inline"
    d.mkdir()
    (d / "a.txt").write_text("oi", encoding="utf-8")
    (d / "b.py").write_text("print(1)\n", encoding="utf-8")

    out = tmp / "saida_inline.md"
    ok = mod.generate_tree_with_content(
        str(d), str(out),
        archive_mode="skip",
        output_mode="inline",
    )
    assert ok is True, "generate_tree_with_content retornou False"
    txt = out.read_text(encoding="utf-8")
    assert "a.txt" in txt, "a.txt não aparece na saída"
    assert "b.py" in txt, "b.py não aparece na saída"


def t_generate_separate(mod, tmp):
    """generate_tree_with_content em modo separate cria a pasta de transcrições."""
    d = tmp / "dir_sep"
    d.mkdir()
    (d / "a.txt").write_text("oi", encoding="utf-8")

    out = tmp / "saida_sep.md"
    ok = mod.generate_tree_with_content(
        str(d), str(out),
        archive_mode="skip",
        output_mode="separate",
    )
    assert ok is True, "generate_tree_with_content retornou False"
    assert out.is_file(), "arquivo .md não foi criado"

    pasta = tmp / "saida_sep_arquivos"
    assert pasta.is_dir(), f"pasta de transcrições não foi criada: {pasta}"

    arquivos = list(pasta.iterdir())
    assert len(arquivos) >= 1, f"nenhum arquivo em {pasta}"


def _criar_projeto_node(tmp):
    """Projeto falso com lixo típico (node_modules, lock, .env, segredos)."""
    raiz = tmp / "proj_filtro"
    if raiz.exists():
        shutil.rmtree(raiz)
    (raiz / "src").mkdir(parents=True)
    (raiz / "api").mkdir()
    (raiz / "docs").mkdir()
    (raiz / "node_modules" / "lodash").mkdir(parents=True)
    (raiz / "dist").mkdir()
    (raiz / "gerado").mkdir()
    (raiz / "src" / "index.ts").write_text("export const ok = 1;\n")
    (raiz / "api" / "server.py").write_text("print('api')\n")
    (raiz / "docs" / "leia.md").write_text("# docs\n")
    (raiz / "node_modules" / "lodash" / "index.js").write_text("module.exports={}\n")
    (raiz / "dist" / "index.js").write_text("compilado\n")
    (raiz / "gerado" / "x.txt").write_text("gerado\n")
    (raiz / "package.json").write_text('{"name":"p"}\n')
    (raiz / "package-lock.json").write_text('{"lockfileVersion":3}\n')
    (raiz / ".env").write_text("SENHA=123\n")
    (raiz / "chave.pem").write_text("-----BEGIN-----\n")
    (raiz / "debug.log").write_text("log\n")
    (raiz / ".gitignore").write_text("gerado/\n")
    return raiz


def _gerar(mod, raiz, tmp, nome, **kw):
    out = tmp / nome
    ok = mod.generate_tree_with_content(str(raiz), str(out), **kw)
    assert ok, "generate_tree_with_content devolveu False"
    return out.read_text(encoding="utf-8")


def t_excludes_padrao(mod, tmp):
    """node_modules, dist, lockfile, .env, .pem e .log ficam de fora."""
    raiz = _criar_projeto_node(tmp)
    md = _gerar(mod, raiz, tmp, "f1.md", include_hidden=True)
    for ausente in ("node_modules", "dist/", "package-lock.json",
                    "SENHA=123", "chave.pem", "debug.log"):
        assert ausente not in md, f"{ausente!r} deveria estar fora"
    for presente in ("index.ts", "server.py", "package.json"):
        assert presente in md, f"{presente!r} deveria estar presente"


def t_respeita_gitignore(mod, tmp):
    """Pasta listada no .gitignore some; --no-gitignore traz de volta."""
    raiz = _criar_projeto_node(tmp)
    md = _gerar(mod, raiz, tmp, "f2.md")
    assert "gerado" not in md, "gerado/ está no .gitignore"
    filtro = mod.PathFilter(str(raiz), respect_gitignore=False)
    md2 = _gerar(mod, raiz, tmp, "f3.md", path_filter=filtro)
    assert "gerado" in md2, "sem gitignore, gerado/ deveria aparecer"


def t_only_paths(mod, tmp):
    """--only limita às pastas pedidas."""
    raiz = _criar_projeto_node(tmp)
    filtro = mod.PathFilter(str(raiz), only=["src", "api"])
    md = _gerar(mod, raiz, tmp, "f4.md", path_filter=filtro)
    assert "index.ts" in md and "server.py" in md
    assert "leia.md" not in md, "docs/ não foi pedido"
    assert "package.json" not in md, "arquivo da raiz não foi pedido"


def t_exclude_extra(mod, tmp):
    """Padrão extra via excludes funciona."""
    raiz = _criar_projeto_node(tmp)
    filtro = mod.PathFilter(str(raiz), excludes=["docs/", "*.py"])
    md = _gerar(mod, raiz, tmp, "f5.md", path_filter=filtro)
    assert "leia.md" not in md and "server.py" not in md
    assert "index.ts" in md


def t_cli_nao_interativo(mod, tmp):
    """main_cli gera o arquivo sem pedir input()."""
    raiz = _criar_projeto_node(tmp)
    out = tmp / "cli.md"
    antigo = builtins.input
    builtins.input = _FakeInput([])  # qualquer input() quebra o teste
    try:
        rc = mod.main_cli([str(raiz), "-o", str(out), "--only", "src"])
    finally:
        builtins.input = antigo
    assert rc == 0, f"rc={rc}"
    md = out.read_text(encoding="utf-8")
    assert "index.ts" in md and "server.py" not in md


# ============================================================
# REGISTRO DOS TESTES
# ============================================================

TESTES = [
    ("detecta zip por magic",              t_detectar_zip),
    ("detecta gzip por magic",             t_detectar_gzip),
    ("detecta tar por magic",              t_detectar_tar),
    ("detecta tgz como gzip (magic)",      t_detectar_tgz_como_gzip),
    ("detecta android-boot por magic",     t_detectar_android_boot),
    ("ZipHandler.listar vê membros",       t_zip_handler_listar),
    ("ZipHandler.ler devolve bytes",       t_zip_handler_ler),
    ("TarHandler.listar vê membros",       t_tar_handler_listar),
    ("Registry escolhe ZipHandler",        t_registry_escolhe_zip),
    ("Registry escolhe TarHandler",        t_registry_escolhe_tar),
    ("Registry reconhece MBR",             t_registry_reconhece_mbr),
    ("symlink circular não trava",         t_symlink_circular),
    ("escape_md funciona",                 t_escape_md),
    ("valid_options é estrito",            t_valid_options_estrito),
    ("generate inline funciona",           t_generate_inline),
    ("generate separate cria pasta",       t_generate_separate),
    ("excludes padrão (node_modules etc.)", t_excludes_padrao),
    ("respeita .gitignore",                t_respeita_gitignore),
    ("only limita pastas",                 t_only_paths),
    ("exclude extra",                      t_exclude_extra),
    ("CLI não interativo",                 t_cli_nao_interativo),
]


# ============================================================
# RUNNER
# ============================================================

def rodar_todos():
    c = _cores()
    print(f"{c['bo']}Tree Content Generator — testes de fumaça{c['end']}")
    print(f"Gerador: {GERADOR}\n")

    mod = _carregar_gerador()
    tmp = Path(tempfile.mkdtemp(prefix="tcg_test_"))

    print(f"{c['bo']}Rodando {len(TESTES)} testes...{c['end']}")
    falhas = []
    passou = 0

    try:
        for nome, fn in TESTES:
            try:
                fn(mod, tmp)
                print(f"  {c['ok']}✓{c['end']} {nome}")
                passou += 1
            except AssertionError as e:
                print(f"  {c['er']}✗{c['end']} {nome}: {e}")
                falhas.append(nome)
            except Exception as e:
                tipo = type(e).__name__
                print(f"  {c['er']}✗{c['end']} {nome}: "
                      f"exceção {tipo}: {e}")
                falhas.append(nome)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print()
    print(f"{c['bo']}Resultado:{c['end']} "
          f"{passou}/{len(TESTES)} passaram, "
          f"{len(falhas)} falharam")

    if falhas:
        print()
        print(f"{c['er']}Testes que falharam:{c['end']}")
        for nome in falhas:
            print(f"  • {nome}")
        return 1

    print(f"{c['ok']}Todos os testes passaram.{c['end']}")
    return 0


# ============================================================
# ENTRY POINT
# ============================================================

if __name__ == "__main__":
    try:
        sys.exit(rodar_todos())
    except KeyboardInterrupt:
        print("\n\nCancelado pelo usuário.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"\nERRO inesperado: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(2)
