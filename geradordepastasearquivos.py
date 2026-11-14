#!/usr/bin/env python3
"""
Tree Content Generator - Versão Interativa (v6)
Gera árvore de diretórios com ou sem transcrição de arquivos para Markdown.

NOVO NA v6 (sobre a v5):
  • AndroidBootHandler     — Android boot image (magic 'ANDROID!')
  • AndroidSparseHandler   — Android sparse image (converte via simg2img,
                             devolve a imagem raw para detecção recursiva)
  • DiskImageHandler       — imagem com tabela MBR/GPT: lista as partições
                             como membros; cada partição é reaberta pelo
                             handler do filesystem interno
  • Correção do bug de cleanup em DiskImageHandler._parse_gpt
  • Correção do bug de cleanup em Registry._handler_img_desconhecido

Novidades da v5 (mantidas):
  • Detecção por magic bytes (não confia só na extensão)
  • Handlers nativos: zip, tar, gzip, bzip2, xz, zstd, ar (e .deb)
  • Handlers externos: 7z, rar, iso, squashfs, img-ext, img-fat
  • Recursão natural: .tgz = gzip → tar; .deb = ar → data.tar.xz → xz → tar

Novidades da v4 (mantidas):
  (a) recursão em containers aninhados até profundidade configurável
  (b) modo "listar apenas" funciona junto com a recursão
  (c) modo "separate": .md enxuto + pasta com um arquivo por transcrição

Correções herdadas da v2/v3 (mantidas):
  valid_options estrito, proteção contra symlinks circulares, sem variável
  global mutável, prompt do root_only correto, datetime em vez de
  os.popen('date'), sockets/FIFOs ignorados, arquivo de saída excluído da
  listagem, saída dos loops por 'sair', extensões sem duplicatas,
  get_file_content devolve (conteudo, erro), escape de Markdown nos nomes,
  contagem rotulada como 'subpastas', espaçamento de emojis normalizado.
"""

import bz2
import gzip
import io
import lzma
import argparse
import fnmatch
import os
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from datetime import datetime


# ============================================
# CONFIGURAÇÕES
# ============================================

TEXT_EXTENSIONS = {
    '.py', '.pyw', '.pyi',
    '.js', '.jsx', '.ts', '.tsx', '.mjs', '.cjs',
    '.rb', '.go', '.rs', '.java', '.kt', '.kts', '.scala',
    '.c', '.h', '.cpp', '.cc', '.cxx', '.hpp', '.hh', '.hxx',
    '.cs', '.swift', '.php', '.pl', '.pm', '.t', '.pod', '.raku',
    '.lua', '.r', '.rmd', '.rnw', '.rprofile', '.jl', '.ipynb',
    '.dart', '.groovy', '.gradle', '.m',
    '.lisp', '.cl', '.el', '.rkt', '.scm',
    '.clj', '.cljs', '.cljc', '.ex', '.exs',
    '.vhd', '.vhdl', '.v', '.sv', '.svh', '.vlog',
    '.tcl', '.tk', '.expect',
    '.html', '.htm', '.xhtml', '.xml', '.svg', '.vue', '.svelte',
    '.css', '.scss', '.sass', '.less', '.styl',
    '.json', '.json5', '.hjson', '.yaml', '.yml', '.toml',
    '.ini', '.cfg', '.conf', '.config', '.properties',
    '.csv', '.tsv', '.tab', '.psv',
    '.sql', '.ddl', '.dml',
    '.log', '.out', '.err',
    '.txt', '.md', '.markdown', '.rst', '.adoc', '.asciidoc',
    '.org', '.wiki', '.tex', '.bib', '.sty', '.cls', '.ltx',
    '.sh', '.bash', '.zsh', '.fish', '.ksh', '.csh',
    '.gitignore', '.gitattributes', '.dockerignore',
    '.eslintignore', '.prettierignore',
    '.env', '.editorconfig', '.bashrc', '.zshrc', '.vimrc', '.inputrc',
}

MAX_FILE_SIZE = 5 * 1024 * 1024
MAX_ARCHIVE_SIZE = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 5000
MAX_ARCHIVE_TOTAL_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_DEPTH = 3
MAX_TRANSCRIPTION_FILENAME = 120

# Padrões ignorados por padrão (sintaxe estilo .gitignore simplificada):
#   - "nome/"  → só pastas com esse nome, em qualquer nível
#   - "*.ext"  → casa com o nome do arquivo/pasta (fnmatch)
#   - "a/b"    → contém '/', casa com o caminho relativo à raiz
DEFAULT_EXCLUDES = [
    # Dependências, builds e caches
    'node_modules/', 'bower_components/', 'jspm_packages/',
    'dist/', 'build/', 'out/', 'coverage/', 'target/',
    'venv/', 'env/', '__pycache__/', 'site-packages/', '*.egg-info/',
    '*.pyc', '*.pyo', '*.class', '*.o', '*.so', '*.dll', '*.exe',
    # Lockfiles e artefatos gerados (grandes e sem valor como contexto)
    '*.lock', 'package-lock.json', 'pnpm-lock.yaml', 'yarn.lock',
    'npm-shrinkwrap.json', '*.min.js', '*.min.css', '*.map', '*.log',
    '*.tsbuildinfo',
    # Bancos locais
    '*.sqlite', '*.sqlite3', '*.db',
    # Segredos
    '.env', '.env.*', '*.env', '*.pem', '*.key', '*.p12', '*.pfx',
    '*.keystore', '*.jks', 'id_rsa*', 'id_ed25519*', '*secret*',
    '*credential*', '.npmrc', '.pypirc', '.netrc',
]


def _ler_gitignore(start_dir):
    """Lê o .gitignore da raiz. Devolve lista de linhas (pode ser vazia)."""
    p = os.path.join(start_dir, '.gitignore')
    try:
        with open(p, 'r', encoding='utf-8', errors='replace') as f:
            return [ln.rstrip('\n') for ln in f]
    except OSError:
        return []


class PathFilter:
    """Decide quais caminhos entram na árvore.

    Combina: padrões de exclusão (DEFAULT_EXCLUDES + extras), o .gitignore
    da raiz (via `pathspec`, se instalado; senão um fallback simples) e
    uma lista opcional `only` de caminhos relativos permitidos.
    """

    def __init__(self, start_dir, excludes=None, use_defaults=True,
                 respect_gitignore=True, only=None):
        self.start_dir = os.path.abspath(start_dir)
        pats = list(DEFAULT_EXCLUDES) if use_defaults else []
        pats += [p.strip() for p in (excludes or []) if p and p.strip()]
        self.patterns = pats
        self.only = [os.path.normpath(o.strip().strip('/'))
                     for o in (only or []) if o and o.strip().strip('/')]
        self._spec = None
        self._gi_fallback = []
        if respect_gitignore:
            linhas = _ler_gitignore(self.start_dir)
            if linhas:
                try:
                    import pathspec
                    self._spec = pathspec.PathSpec.from_lines(
                        'gitwildmatch', linhas)
                except ImportError:
                    # Fallback: ignora negações e comentários
                    self._gi_fallback = [
                        ln.strip() for ln in linhas
                        if ln.strip() and not ln.lstrip().startswith(('#', '!'))
                    ]

    @staticmethod
    def _casa(pat, nome, rel, is_dir):
        if pat.endswith('/'):
            if not is_dir:
                return False
            pat = pat.rstrip('/')
        ancorado = pat.startswith('/')
        pat = pat.lstrip('/')
        if '/' in pat or ancorado:
            return fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat + '/*')
        return fnmatch.fnmatch(nome, pat)

    def _dentro_de_only(self, rel, is_dir):
        if not self.only:
            return True
        for o in self.only:
            if rel == o or rel.startswith(o + os.sep):
                return True  # dentro de uma pasta permitida
            if is_dir and o.startswith(rel + os.sep):
                return True  # ancestral de uma pasta permitida
        return False

    def permitido(self, full):
        full = os.path.abspath(full)
        rel = os.path.relpath(full, self.start_dir)
        if rel == '.':
            return True
        nome = os.path.basename(full)
        is_dir = os.path.isdir(full)
        rel_posix = rel.replace(os.sep, '/')
        for pat in self.patterns:
            if self._casa(pat, nome, rel_posix, is_dir):
                return False
        if self._spec is not None:
            if self._spec.match_file(rel_posix + ('/' if is_dir else '')):
                return False
        for pat in self._gi_fallback:
            if self._casa(pat, nome, rel_posix, is_dir):
                return False
        return self._dentro_de_only(rel, is_dir)


class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    END = '\033[0m'
    BOLD = '\033[1m'


# ============================================
# HELPERS BÁSICOS
# ============================================

class UserCancelled(Exception):
    pass


def print_header(t):
    print(f"\n{Colors.CYAN}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{t:^60}{Colors.END}")
    print(f"{Colors.CYAN}{'='*60}{Colors.END}\n")


def print_success(t):
    print(f"{Colors.GREEN}✅ {t}{Colors.END}")


def print_error(t):
    print(f"{Colors.RED}❌ {t}{Colors.END}")


def print_info(t):
    print(f"{Colors.BLUE}ℹ️ {t}{Colors.END}")


def print_warning(t):
    print(f"{Colors.YELLOW}⚠️ {t}{Colors.END}")


def escape_md(text):
    for ch in ("\\", "`", "*", "_", "[", "]", "|"):
        text = text.replace(ch, "\\" + ch)
    return text


def _formata_tamanho(n):
    if n is None or n < 0:
        return "?"
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.1f} GB"


def _agora():
    return datetime.now().astimezone().strftime("%a %d %b %Y %H:%M:%S %z")


def get_input(prompt, default=None, input_type=str, valid_options=None):
    while True:
        if default is not None:
            if isinstance(default, bool):
                dstr = "s" if default else "n"
            else:
                dstr = str(default)
            full = f"{prompt} [{dstr}]: "
        else:
            full = f"{prompt}: "
        try:
            v = input(full).strip()
        except EOFError:
            raise UserCancelled("Entrada encerrada (EOF).")
        if v.lower() in ("sair", "cancelar", "q", "quit", "exit"):
            raise UserCancelled("Cancelado pelo usuário.")
        if not v and default is not None:
            v = str(default)
        if valid_options:
            if v.lower() in [o.lower() for o in valid_options]:
                return v
            print_error("Opção inválida! Tente novamente.")
            continue
        try:
            if input_type == bool:
                return v.lower() in ('s', 'sim', 'y', 'yes', 'true', '1')
            if input_type == int:
                return int(v)
            return v
        except ValueError:
            print_error("Valor inválido! Tente novamente.")


def get_directory_path():
    while True:
        p = get_input("📁 Caminho do diretório (ou 'sair' para cancelar)",
                      default=".")
        if os.path.isdir(p):
            return os.path.abspath(p)
        print_error(f"Diretório não encontrado: {p}")


def get_output_filename():
    while True:
        n = get_input("📄 Nome do arquivo de saída (ou 'sair' para cancelar)",
                      default="estrutura_completa.md")
        if not n.endswith('.md'):
            n += '.md'
        if os.path.exists(n):
            if get_input(f"⚠️ '{n}' já existe. Sobrescrever?",
                         default=False, input_type=bool):
                return n
            print_info("Digite outro nome ou 'sair' para cancelar.")
        else:
            return n


# ============================================
# DETECÇÃO POR MAGIC BYTES
# ============================================

MAGIC = [
    (0,     b'PK\x03\x04',                'zip'),
    (0,     b'PK\x05\x06',                'zip'),
    (0,     b'PK\x07\x08',                'zip'),
    (0,     b'\x1f\x8b',                  'gzip'),
    (0,     b'BZh',                       'bzip2'),
    (0,     b'\xfd7zXZ\x00',              'xz'),
    (0,     b'\x28\xb5\x2f\xfd',          'zstd'),
    (0,     b'7z\xbc\xaf\x27\x1c',        '7z'),
    (0,     b'Rar!\x1a\x07',              'rar'),
    (0,     b'!<arch>\n',                 'ar'),
    (0,     b'hsqs',                      'squashfs'),
    (0,     b'sqsh',                      'squashfs'),
    (0,     b'ANDROID!',                  'android-boot'),
    (0,     b'\x3a\xff\x26\xed',          'android-sparse'),
    (0,     b'\xed\x26\xff\x3a',          'android-sparse'),
    (0,     b'-rom1fs-',                  'romfs'),
    (0,     b'\x89HDF\r\n\x1a\n',         'hdf5'),
    (257,   b'ustar',                     'tar'),
    (512,   b'EFI PART',                  'gpt'),
    (32769, b'CD001',                     'iso'),
    (1080,  b'\x53\xef',                  'ext'),
]

EXT_HINTS = {
    '.zip': 'zip', '.jar': 'zip', '.war': 'zip', '.ear': 'zip',
    '.apk': 'zip', '.epub': 'zip', '.docx': 'zip', '.xlsx': 'zip',
    '.pptx': 'zip', '.odt': 'zip', '.ods': 'zip', '.odp': 'zip',
    '.whl': 'zip', '.egg': 'zip', '.nupkg': 'zip', '.xpi': 'zip',
    '.crx': 'zip', '.vsix': 'zip', '.appx': 'zip', '.ipa': 'zip',
    '.cbz': 'zip',
    '.tar': 'tar', '.tgz': 'tar', '.tbz2': 'tar', '.txz': 'tar',
    '.tzst': 'tar', '.crate': 'tar', '.gem': 'tar', '.ipk': 'tar',
    '.tar.gz': 'tar', '.tar.bz2': 'tar', '.tar.xz': 'tar', '.tar.zst': 'tar',
    '.gz': 'gzip', '.bz2': 'bzip2', '.xz': 'xz', '.zst': 'zstd',
    '.deb': 'ar', '.a': 'ar', '.ar': 'ar',
    '.7z': '7z', '.rar': 'rar', '.iso': 'iso',
    '.squashfs': 'squashfs', '.sqfs': 'squashfs', '.sfs': 'squashfs',
    '.img': 'img',
}


def detectar_formato_por_magic(source):
    """
    Lê os primeiros bytes e devolve o nome do formato ou None.
    Aceita str (path) ou BytesIO.
    """
    try:
        if isinstance(source, str):
            with open(source, 'rb') as f:
                buf = f.read(32773)
        else:
            pos = source.tell()
            source.seek(0)
            buf = source.read(32773)
            source.seek(pos)
    except (OSError, ValueError):
        return None
    for offset, sig, nome in MAGIC:
        if buf[offset:offset + len(sig)] == sig:
            return nome
    return None


def detectar_formato(source, nome_original=None):
    fmt = detectar_formato_por_magic(source)
    if fmt:
        return fmt
    nome = nome_original or (source if isinstance(source, str) else "")
    if not nome:
        return None
    lower = nome.lower()
    for suf in ('.tar.gz', '.tar.bz2', '.tar.xz', '.tar.zst'):
        if lower.endswith(suf):
            return 'tar'
    ext = os.path.splitext(lower)[1]
    return EXT_HINTS.get(ext)


# ============================================
# DESCOBERTA DE FERRAMENTAS EXTERNAS
# ============================================

class Ferramentas:
    _cache = None

    @classmethod
    def detectar(cls):
        if cls._cache is not None:
            return cls._cache
        cls._cache = {
            '7z':         cls._primeiro(['7z', '7za', '7zr', '7zz']),
            'unrar':      cls._primeiro(['unrar', 'unar', 'bsdtar']),
            'isoinfo':    cls._primeiro(['isoinfo']),
            'unsquashfs': shutil.which('unsquashfs'),
            'debugfs':    shutil.which('debugfs'),
            'mdir':       shutil.which('mdir'),
            'simg2img':   shutil.which('simg2img'),
            'file':       shutil.which('file'),
            'py7zr':      cls._tem_python('py7zr'),
            'pycdlib':    cls._tem_python('pycdlib'),
            'zstandard':  cls._tem_python('zstandard'),
        }
        return cls._cache

    @staticmethod
    def _primeiro(candidatos):
        for c in candidatos:
            if shutil.which(c):
                return c
        return None

    @staticmethod
    def _tem_python(modulo):
        try:
            __import__(modulo)
            return modulo
        except ImportError:
            return None


def resumo_ferramentas():
    t = Ferramentas.detectar()
    linhas = []
    linhas.append(("zip",           "✓ nativo (zipfile)"))
    linhas.append(("tar",           "✓ nativo (tarfile)"))
    linhas.append(("gzip/bzip2/xz", "✓ nativo"))
    linhas.append(("zstd",          f"✓ {t['zstandard']}" if t['zstandard']
                                     else "✗ instale 'zstandard' (pip) ou 'zstd'"))
    linhas.append(("ar/.deb",       "✓ nativo"))
    linhas.append(("android-boot",  "✓ nativo"))
    linhas.append(("android-sparse",f"✓ {t['simg2img']}" if t['simg2img']
                                     else "✗ instale: apt install simg2img"))
    linhas.append(("MBR/GPT",       "✓ nativo"))
    for nome, chave, dica in [
        ("7z",        "7z",         "apt install p7zip-full"),
        ("rar",       "unrar",      "apt install unrar (ou 'unar')"),
        ("iso",       "isoinfo",    "apt install genisoimage (ou pycdlib)"),
        ("squashfs",  "unsquashfs", "apt install squashfs-tools"),
        ("img (ext)", "debugfs",    "apt install e2fsprogs"),
        ("img (fat)", "mdir",       "apt install mtools"),
    ]:
        valor = t.get(chave)
        if valor:
            linhas.append((nome, f"✓ {valor}"))
        else:
            linhas.append((nome, f"✗ instale: {dica}"))
    return linhas


# ============================================
# HANDLERS
# ============================================

class Handler:
    nome = '?'
    nativo = True
    recursivo = True

    def disponivel(self):
        return True

    def listar(self, source):
        raise NotImplementedError

    def ler(self, source, nome):
        raise NotImplementedError

    def _como_caminho(self, source):
        if isinstance(source, str):
            return source, (lambda: None)
        fd, tmp = tempfile.mkstemp(prefix='tcg_', suffix='.bin')
        try:
            with os.fdopen(fd, 'wb') as f:
                pos = source.tell()
                source.seek(0)
                shutil.copyfileobj(source, f)
                source.seek(pos)
        except Exception:
            os.unlink(tmp)
            raise
        return tmp, (lambda: os.path.exists(tmp) and os.unlink(tmp))


class ZipHandler(Handler):
    nome, nativo, recursivo = 'zip', True, True

    def listar(self, source):
        try:
            with zipfile.ZipFile(source) as z:
                return [(i.filename, i.file_size,
                         i.is_dir() or i.filename.endswith('/'))
                        for i in z.infolist()][:MAX_ARCHIVE_MEMBERS]
        except (zipfile.BadZipFile, OSError, EOFError):
            return []

    def ler(self, source, nome):
        try:
            with zipfile.ZipFile(source) as z:
                return z.read(nome)
        except (KeyError, zipfile.BadZipFile, OSError):
            return None


def _abrir_tar(source):
    if isinstance(source, str):
        return tarfile.open(source, 'r:*')
    return tarfile.open(fileobj=source, mode='r:*')


class TarHandler(Handler):
    nome, nativo, recursivo = 'tar', True, True

    def listar(self, source):
        try:
            with _abrir_tar(source) as t:
                return [(m.name, m.size, m.isdir())
                        for m in t.getmembers()][:MAX_ARCHIVE_MEMBERS]
        except (tarfile.TarError, OSError, EOFError):
            return []

    def ler(self, source, nome):
        try:
            with _abrir_tar(source) as t:
                m = t.getmember(nome)
                f = t.extractfile(m)
                return f.read() if f else None
        except (KeyError, tarfile.TarError, OSError):
            return None


class StreamHandler(Handler):
    nome, nativo, recursivo = '?', True, True
    sufixos = ()

    def _nome_virtual(self, source):
        nome = source if isinstance(source, str) else '<stream>'
        base = os.path.basename(nome)
        for suf in self.sufixos:
            if base.lower().endswith(suf):
                return base[:-len(suf)] or base
        return base + '.descomprimido'

    def listar(self, source):
        return [(self._nome_virtual(source), -1, False)]

    def _descomprimir(self, source):
        raise NotImplementedError

    def ler(self, source, nome):
        return self._descomprimir(source)


class GzipHandler(StreamHandler):
    nome, sufixos = 'gzip', ('.gz', '.tgz')

    def _descomprimir(self, source):
        try:
            if isinstance(source, str):
                with gzip.open(source, 'rb') as f:
                    return f.read()
            source.seek(0)
            return gzip.decompress(source.read())
        except (OSError, EOFError, gzip.BadGzipFile):
            return None


class Bzip2Handler(StreamHandler):
    nome, sufixos = 'bzip2', ('.bz2', '.tbz2')

    def _descomprimir(self, source):
        try:
            if isinstance(source, str):
                with bz2.open(source, 'rb') as f:
                    return f.read()
            source.seek(0)
            return bz2.decompress(source.read())
        except (OSError, EOFError):
            return None


class XzHandler(StreamHandler):
    nome, sufixos = 'xz', ('.xz', '.txz', '.lzma')

    def _descomprimir(self, source):
        try:
            if isinstance(source, str):
                with lzma.open(source, 'rb') as f:
                    return f.read()
            source.seek(0)
            return lzma.decompress(source.read())
        except (OSError, EOFError, lzma.LZMAError):
            return None


class ZstdHandler(StreamHandler):
    nome, sufixos = 'zstd', ('.zst', '.tzst')

    def disponivel(self):
        return Ferramentas.detectar()['zstandard'] is not None

    def _descomprimir(self, source):
        try:
            import zstandard as zstd
            dctx = zstd.ZstdDecompressor()
            if isinstance(source, str):
                with open(source, 'rb') as f:
                    return dctx.decompress(f.read(),
                                           max_output_size=64 * 1024 * 1024)
            source.seek(0)
            return dctx.decompress(source.read(),
                                   max_output_size=64 * 1024 * 1024)
        except Exception:
            return None


class ArHandler(Handler):
    nome, nativo, recursivo = 'ar', True, True

    @staticmethod
    def _parse(source):
        if isinstance(source, str):
            f = open(source, 'rb')
            cleanup = f.close
        else:
            source.seek(0)
            f = source
            cleanup = lambda: None
        try:
            if f.read(8) != b'!<arch>\n':
                return []
            entradas = []
            offset = 8
            while True:
                header = f.read(60)
                if len(header) < 60:
                    break
                nome_raw = header[0:16].decode('latin-1').rstrip()
                nome = nome_raw.rstrip('/')
                try:
                    tam = int(header[48:58].decode('ascii').rstrip())
                except ValueError:
                    break
                if nome in ('/', '//'):
                    offset += 60 + tam + (tam % 2)
                    f.seek(offset)
                    continue
                if header[58:60] != b'`\n':
                    break
                entradas.append((nome, offset + 60, tam))
                offset += 60 + tam + (tam % 2)
                f.seek(offset)
            return entradas
        finally:
            cleanup()

    def listar(self, source):
        return [(n, t, False) for n, o, t in self._parse(source)]

    def ler(self, source, nome):
        for n, o, t in self._parse(source):
            if n == nome:
                if isinstance(source, str):
                    with open(source, 'rb') as f:
                        f.seek(o)
                        return f.read(t)
                else:
                    source.seek(o)
                    return source.read(t)
        return None


class SevenZipHandler(Handler):
    nome, nativo, recursivo = '7z', False, True

    def _tool(self):
        return Ferramentas.detectar()['7z']

    def disponivel(self):
        return self._tool() is not None

    def listar(self, source):
        caminho, cleanup = self._como_caminho(source)
        try:
            r = subprocess.run([self._tool(), 'l', '-ba', '-slt', caminho],
                               capture_output=True, text=True, timeout=120)
            if r.returncode != 0:
                return []
            entradas = []
            atual = {}
            for linha in r.stdout.splitlines():
                if not linha.strip():
                    if 'Path' in atual and 'Size' in atual:
                        attrs = atual.get('Attributes', '')
                        is_dir = ('D' in attrs)
                        try:
                            tam = int(atual.get('Size', '0') or 0)
                        except ValueError:
                            tam = 0
                        entradas.append((atual['Path'], tam, is_dir))
                    atual = {}
                    continue
                if ' = ' in linha:
                    k, v = linha.split(' = ', 1)
                    atual[k.strip()] = v.strip()
            return entradas[:MAX_ARCHIVE_MEMBERS]
        except (subprocess.TimeoutExpired, OSError):
            return []
        finally:
            cleanup()

    def ler(self, source, nome):
        caminho, cleanup = self._como_caminho(source)
        try:
            r = subprocess.run([self._tool(), 'x', '-so', caminho, nome],
                               capture_output=True, timeout=120)
            return r.stdout if r.returncode == 0 else None
        except (subprocess.TimeoutExpired, OSError):
            return None
        finally:
            cleanup()


class IsoHandler(Handler):
    nome, nativo, recursivo = 'iso', False, True

    def _usar_pycdlib(self):
        return Ferramentas.detectar()['pycdlib'] is not None

    def disponivel(self):
        return self._usar_pycdlib() or Ferramentas.detectar()['isoinfo'] is not None

    def listar(self, source):
        if self._usar_pycdlib():
            return self._listar_pycdlib(source)
        return self._listar_isoinfo(source)

    def _listar_pycdlib(self, source):
        try:
            import pycdlib
        except ImportError:
            return []
        caminho, cleanup = self._como_caminho(source)
        iso = pycdlib.PyCdlib()
        entradas = []
        try:
            iso.open(caminho)

            def visitar(pasta, prefixo=''):
                for filho in pasta.children:
                    nome = filho.file_identifier().decode('latin-1').split(';')[0]
                    caminho_virtual = f"{prefixo}{nome}"
                    if filho.is_dir():
                        entradas.append((caminho_virtual + '/', 0, True))
                        visitar(filho, caminho_virtual + '/')
                    else:
                        tam = getattr(filho, 'data_length', 0) or 0
                        entradas.append((caminho_virtual, tam, False))

            visitar(iso.get_root_dir())
            return entradas[:MAX_ARCHIVE_MEMBERS]
        except Exception:
            return []
        finally:
            try:
                iso.close()
            except Exception:
                pass
            cleanup()

    def _listar_isoinfo(self, source):
        caminho, cleanup = self._como_caminho(source)
        try:
            r = subprocess.run([Ferramentas.detectar()['isoinfo'], '-l', '-i', caminho],
                               capture_output=True, text=True, timeout=120)
            entradas = []
            for linha in r.stdout.splitlines():
                if linha.startswith('d') or linha.startswith('-'):
                    partes = linha.split(None, 4)
                    if len(partes) == 5:
                        try:
                            tam = int(partes[3].split(' ')[0].strip() or 0)
                        except (ValueError, IndexError):
                            tam = 0
                        nome = partes[4].split()[-1]
                        is_dir = linha.startswith('d')
                        entradas.append((nome, tam, is_dir))
            return entradas[:MAX_ARCHIVE_MEMBERS]
        except (subprocess.TimeoutExpired, OSError):
            return []
        finally:
            cleanup()

    def ler(self, source, nome):
        return None


class SquashfsHandler(Handler):
    nome, nativo, recursivo = 'squashfs', False, True

    def disponivel(self):
        return Ferramentas.detectar()['unsquashfs'] is not None

    def _tool(self):
        return Ferramentas.detectar()['unsquashfs']

    def listar(self, source):
        caminho, cleanup = self._como_caminho(source)
        try:
            r = subprocess.run([self._tool(), '-l', '-n', caminho],
                               capture_output=True, text=True, timeout=180)
            entradas = []
            for linha in r.stdout.splitlines():
                linha = linha.strip()
                if not linha or not linha.startswith('squashfs-root'):
                    continue
                resto = linha.split('squashfs-root/', 1)
                if len(resto) != 2:
                    continue
                nome = resto[1]
                if not nome:
                    continue
                base = os.path.basename(nome.rstrip('/'))
                is_dir = nome.endswith('/') or ('.' not in base and base != '')
                entradas.append((nome, -1, is_dir))
            return entradas[:MAX_ARCHIVE_MEMBERS]
        except (subprocess.TimeoutExpired, OSError):
            return []
        finally:
            cleanup()

    def ler(self, source, nome):
        return None


class ExtHandler(Handler):
    nome, nativo, recursivo = 'ext', False, True

    def disponivel(self):
        return Ferramentas.detectar()['debugfs'] is not None

    def _tool(self):
        return Ferramentas.detectar()['debugfs']

    def listar(self, source):
        caminho, cleanup = self._como_caminho(source)
        try:
            entradas = []
            self._walk_debugfs(caminho, '/', '', entradas, 0)
            return entradas[:MAX_ARCHIVE_MEMBERS]
        finally:
            cleanup()

    def _walk_debugfs(self, caminho, diretorio, prefixo, entradas, nivel):
        if nivel > 12 or len(entradas) > MAX_ARCHIVE_MEMBERS:
            return
        try:
            r = subprocess.run(
                [self._tool(), '-R', f'ls -l -p {diretorio}', caminho],
                capture_output=True, text=True, timeout=60)
        except (subprocess.TimeoutExpired, OSError):
            return
        for linha in r.stdout.splitlines():
            linha = linha.strip()
            if not linha or linha.startswith('debugfs') or linha.isdigit():
                continue
            partes = linha.split()
            if len(partes) < 8:
                continue
            try:
                modo_str = partes[0]
                tam = int(partes[3]) if partes[3].isdigit() else 0
            except (ValueError, IndexError):
                continue
            nome = ' '.join(partes[7:])
            is_dir = modo_str.startswith('d')
            if nome in ('.', '..'):
                continue
            caminho_v = f"{prefixo}{nome}"
            if is_dir:
                entradas.append((caminho_v + '/', 0, True))
                self._walk_debugfs(caminho, f"{diretorio.rstrip('/')}/{nome}",
                                   caminho_v + '/', entradas, nivel + 1)
            else:
                entradas.append((caminho_v, tam, False))

    def ler(self, source, nome):
        caminho, cleanup = self._como_caminho(source)
        try:
            r = subprocess.run(
                [self._tool(), '-R', f'cat {nome}', caminho],
                capture_output=True, timeout=60)
            return r.stdout if r.returncode == 0 else None
        except (subprocess.TimeoutExpired, OSError):
            return None
        finally:
            cleanup()


class FatHandler(Handler):
    nome, nativo, recursivo = 'fat', False, True

    def disponivel(self):
        return Ferramentas.detectar()['mdir'] is not None

    def _tool(self):
        return Ferramentas.detectar()['mdir']

    def listar(self, source):
        caminho, cleanup = self._como_caminho(source)
        try:
            entradas = []
            self._walk_mdir(caminho, '::/', '', entradas, 0)
            return entradas[:MAX_ARCHIVE_MEMBERS]
        finally:
            cleanup()

    def _walk_mdir(self, caminho, pasta, prefixo, entradas, nivel):
        if nivel > 12 or len(entradas) > MAX_ARCHIVE_MEMBERS:
            return
        try:
            r = subprocess.run(
                [self._tool(), '-i', caminho, '-b', '-/',
                 pasta.rstrip('/') or '::/'],
                capture_output=True, text=True, timeout=60)
        except (subprocess.TimeoutExpired, OSError):
            return
        for linha in r.stdout.splitlines():
            linha = linha.strip()
            if not linha or linha == '/':
                continue
            nome_limpo = linha.lstrip('/').rstrip('/')
            if not nome_limpo:
                continue
            is_dir = linha.endswith('/') or linha.endswith('\\')
            caminho_v = f"{prefixo}{nome_limpo}"
            if is_dir:
                entradas.append((caminho_v + '/', 0, True))
                self._walk_mdir(caminho, f"{pasta.rstrip('/')}/{nome_limpo}",
                                caminho_v + '/', entradas, nivel + 1)
            else:
                entradas.append((caminho_v, -1, False))

    def ler(self, source, nome):
        return None


class AndroidBootHandler(Handler):
    nome, nativo, recursivo = 'android-boot', True, True

    def _header(self, source):
        try:
            if isinstance(source, str):
                with open(source, 'rb') as f:
                    h = f.read(4096)
            else:
                pos = source.tell()
                source.seek(0)
                h = source.read(4096)
                source.seek(pos)
        except (OSError, ValueError):
            return None
        if h[:8] != b'ANDROID!':
            return None
        try:
            campos = struct.unpack('<10I', h[8:48])
        except struct.error:
            return None
        return {
            'kernel_size':  campos[0],
            'ramdisk_size': campos[2],
            'second_size':  campos[4],
            'page_size':    campos[7] or 2048,
            'header_ver':   campos[8],
        }

    @staticmethod
    def _pag(n, page):
        return (n + page - 1) // page * page

    def _secoes(self, info):
        page = info['page_size']
        out = []
        off = page
        if info['kernel_size']:
            out.append(('kernel', off, info['kernel_size']))
        off += self._pag(info['kernel_size'], page)
        if info['ramdisk_size']:
            out.append(('ramdisk', off, info['ramdisk_size']))
        off += self._pag(info['ramdisk_size'], page)
        if info['second_size']:
            out.append(('second', off, info['second_size']))
        return out

    def listar(self, source):
        info = self._header(source)
        if not info:
            return []
        return [(n, t, False) for n, o, t in self._secoes(info)]

    def ler(self, source, nome):
        info = self._header(source)
        if not info:
            return None
        for n, off, tam in self._secoes(info):
            if n != nome:
                continue
            try:
                if isinstance(source, str):
                    with open(source, 'rb') as f:
                        f.seek(off)
                        return f.read(tam)
                source.seek(off)
                return source.read(tam)
            except (OSError, ValueError):
                return None
        return None


class AndroidSparseHandler(Handler):
    nome, nativo, recursivo = 'android-sparse', False, True

    def disponivel(self):
        return Ferramentas.detectar()['simg2img'] is not None

    def _preparar_entrada(self, source):
        if isinstance(source, str):
            return source, (lambda: None)
        fd, tmp = tempfile.mkstemp(prefix='tcg_sparse_in_', suffix='.img')
        try:
            with os.fdopen(fd, 'wb') as f:
                pos = source.tell()
                source.seek(0)
                shutil.copyfileobj(source, f)
                source.seek(pos)
        except Exception:
            os.unlink(tmp)
            raise
        return tmp, (lambda: os.path.exists(tmp) and os.unlink(tmp))

    def _converter(self, source):
        entrada, cleanup_in = self._preparar_entrada(source)
        fd, saida = tempfile.mkstemp(prefix='tcg_sparse_raw_', suffix='.img')
        os.close(fd)
        try:
            r = subprocess.run(['simg2img', entrada, saida],
                               capture_output=True, timeout=600)
            if r.returncode != 0:
                if os.path.exists(saida):
                    os.unlink(saida)
                cleanup_in()
                return None, (lambda: None)
        except (subprocess.TimeoutExpired, OSError):
            if os.path.exists(saida):
                os.unlink(saida)
            cleanup_in()
            return None, (lambda: None)

        def cleanup():
            if os.path.exists(saida):
                os.unlink(saida)
            cleanup_in()

        return saida, cleanup

    def listar(self, source):
        return [('imagem-raw.img', -1, False)]

    def ler(self, source, nome):
        caminho, cleanup = self._converter(source)
        if not caminho:
            return None
        try:
            with open(caminho, 'rb') as f:
                return f.read()
        except OSError:
            return None
        finally:
            cleanup()


class DiskImageHandler(Handler):
    nome, nativo, recursivo = 'disk', True, True

    def _parse_gpt(self, source):
        try:
            if isinstance(source, str):
                with open(source, 'rb') as f:
                    f.seek(512)
                    header = f.read(92)
                    if header[:8] != b'EFI PART':
                        return []
                    try:
                        entry_lba = struct.unpack('<Q', header[72:80])[0]
                        num = struct.unpack('<I', header[80:84])[0]
                        entry_size = struct.unpack('<I', header[84:88])[0]
                    except struct.error:
                        return []
                    if entry_size < 128 or entry_size > 4096 or num > 512:
                        return []
                    f.seek(entry_lba * 512)
                    out = []
                    for i in range(num):
                        entry = f.read(entry_size)
                        if len(entry) < 128:
                            break
                        if entry[:16] == b'\x00' * 16:
                            continue
                        try:
                            first_lba, last_lba = struct.unpack('<QQ', entry[32:48])
                        except struct.error:
                            continue
                        nome_utf16 = entry[56:128].decode('utf-16-le',
                                                          errors='replace')
                        nome = nome_utf16.rstrip('\x00').strip() or f'part{i+1}'
                        out.append((nome, first_lba * 512,
                                    (last_lba - first_lba + 1) * 512))
                    return out
            else:
                pos = source.tell()
                source.seek(512)
                header = source.read(92)
                if header[:8] != b'EFI PART':
                    source.seek(pos)
                    return []
                try:
                    entry_lba = struct.unpack('<Q', header[72:80])[0]
                    num = struct.unpack('<I', header[80:84])[0]
                    entry_size = struct.unpack('<I', header[84:88])[0]
                except struct.error:
                    source.seek(pos)
                    return []
                if entry_size < 128 or entry_size > 4096 or num > 512:
                    source.seek(pos)
                    return []
                source.seek(entry_lba * 512)
                out = []
                for i in range(num):
                    entry = source.read(entry_size)
                    if len(entry) < 128:
                        break
                    if entry[:16] == b'\x00' * 16:
                        continue
                    try:
                        first_lba, last_lba = struct.unpack('<QQ', entry[32:48])
                    except struct.error:
                        continue
                    nome_utf16 = entry[56:128].decode('utf-16-le',
                                                      errors='replace')
                    nome = nome_utf16.rstrip('\x00').strip() or f'part{i+1}'
                    out.append((nome, first_lba * 512,
                                (last_lba - first_lba + 1) * 512))
                source.seek(pos)
                return out
        except (OSError, ValueError):
            return []

    def _parse_mbr(self, source):
        try:
            if isinstance(source, str):
                with open(source, 'rb') as f:
                    mbr = f.read(512)
            else:
                pos = source.tell()
                source.seek(0)
                mbr = source.read(512)
                source.seek(pos)
            if len(mbr) < 512 or mbr[510:512] != b'\x55\xaa':
                return []
            out = []
            for i in range(4):
                entry = mbr[446 + i * 16: 446 + (i + 1) * 16]
                tipo = entry[4]
                if tipo == 0:
                    continue
                try:
                    lba, num = struct.unpack('<II', entry[8:16])
                except struct.error:
                    continue
                if num == 0:
                    continue
                out.append((f'part{i+1}_tipo{tipo:02x}',
                            lba * 512, num * 512))
            return out
        except (OSError, ValueError):
            return []

    def _particoes(self, source):
        gpt = self._parse_gpt(source)
        if gpt:
            return gpt
        return self._parse_mbr(source)

    def listar(self, source):
        return [(n, t, False) for n, o, t in self._particoes(source)]

    def ler(self, source, nome):
        for n, off, tam in self._particoes(source):
            if n != nome:
                continue
            try:
                if isinstance(source, str):
                    with open(source, 'rb') as f:
                        f.seek(off)
                        return f.read(tam)
                pos = source.tell()
                source.seek(off)
                dados = source.read(tam)
                source.seek(pos)
                return dados
            except (OSError, ValueError):
                return None
        return None


# ============================================
# REGISTRY
# ============================================

class Registry:
    def __init__(self):
        self._handlers = {}
        classes = (
            ZipHandler, TarHandler, GzipHandler, Bzip2Handler,
            XzHandler, ZstdHandler, ArHandler,
            SevenZipHandler, IsoHandler, SquashfsHandler,
            ExtHandler, FatHandler,
            AndroidBootHandler, AndroidSparseHandler, DiskImageHandler,
        )
        for cls in classes:
            h = cls()
            self._handlers[cls.nome] = h

    def get(self, fmt):
        return self._handlers.get(fmt)

    def escolher(self, source, nome_original=None):
        fmt = detectar_formato(source, nome_original)
        if fmt == 'ext':
            return self._handlers.get('ext')
        if fmt == 'iso':
            return self._handlers.get('iso')
        if fmt == 'squashfs':
            return self._handlers.get('squashfs')
        if fmt in ('7z', 'rar'):
            return self._handlers.get('7z')
        if fmt == 'android-boot':
            return self._handlers.get('android-boot')
        if fmt == 'android-sparse':
            return self._handlers.get('android-sparse')
        if fmt == 'gpt':
            return self._handlers.get('disk')
        if fmt and fmt != 'img':
            return self._handlers.get(fmt)

        nome = (nome_original or '').lower()
        if nome.endswith('.img') or nome.endswith('.bin') or fmt == 'img':
            try:
                if isinstance(source, str):
                    with open(source, 'rb') as f:
                        f.seek(510)
                        sig = f.read(2)
                else:
                    pos = source.tell()
                    source.seek(510)
                    sig = source.read(2)
                    source.seek(pos)
                if sig == b'\x55\xaa':
                    return self._handlers.get('disk')
            except (OSError, ValueError):
                pass
            return self._handler_img_desconhecido(source)
        return None

    def _handler_img_desconhecido(self, source):
        if not Ferramentas.detectar()['file']:
            return None
        if isinstance(source, str):
            caminho = source
            cleanup = lambda: None
        else:
            fd, tmp = tempfile.mkstemp(prefix='tcg_img_', suffix='.img')
            try:
                with os.fdopen(fd, 'wb') as f:
                    pos = source.tell()
                    source.seek(0)
                    shutil.copyfileobj(source, f)
                    source.seek(pos)
            except Exception:
                os.unlink(tmp)
                return None
            caminho = tmp
            cleanup = lambda: os.path.exists(tmp) and os.unlink(tmp)
        try:
            r = subprocess.run(['file', '-b', caminho],
                               capture_output=True, text=True, timeout=30)
            descricao = r.stdout.lower()
            if 'fat' in descricao or 'msdos' in descricao:
                return self._handlers.get('fat')
            if 'ext' in descricao and 'filesystem' in descricao:
                return self._handlers.get('ext')
            if 'squashfs' in descricao:
                return self._handlers.get('squashfs')
            if 'iso 9660' in descricao:
                return self._handlers.get('iso')
        except (subprocess.TimeoutExpired, OSError):
            pass
        finally:
            cleanup()
        return None


REGISTRY = Registry()


# ============================================
# TIPOS DE ARQUIVO (FS)
# ============================================

def _eh_arquivo_regular(path):
    try:
        return stat.S_ISREG(os.lstat(path).st_mode)
    except OSError:
        return False


def is_text_file(path):
    if not _eh_arquivo_regular(path):
        return False
    ext = os.path.splitext(path)[1].lower()
    if ext in TEXT_EXTENSIONS:
        return True
    try:
        with open(path, 'rb') as f:
            chunk = f.read(1024)
        try:
            chunk.decode('utf-8')
            return True
        except UnicodeDecodeError:
            return b'\0' not in chunk
    except OSError:
        return False


def get_file_content(path, max_lines=None, max_size=MAX_FILE_SIZE):
    try:
        tam = os.path.getsize(path)
        if tam > max_size:
            return (f"[⚠️ Arquivo grande ({_formata_tamanho(tam)}) — "
                    "não transcrito]", True)
        try:
            with open(path, 'rb') as fb:
                if b'\0' in fb.read(2048):
                    return ("[⚠️ Conteúdo binário (NUL) — não transcrito]", True)
        except OSError:
            pass
        for enc in ('utf-8', 'latin-1', 'cp1252', 'iso-8859-1'):
            try:
                with open(path, 'r', encoding=enc) as f:
                    if max_lines:
                        linhas = []
                        for i, ln in enumerate(f):
                            if i >= max_lines:
                                linhas.append(
                                    f"... (continuação, {max_lines} linhas mostradas)")
                                break
                            linhas.append(ln.rstrip('\n'))
                        return ('\n'.join(linhas), False)
                    return (f.read(), False)
            except UnicodeDecodeError:
                continue
        return ("[⚠️ Não foi possível decodificar o arquivo]", True)
    except PermissionError:
        return ("[⚠️ Sem permissão]", True)
    except OSError as e:
        return (f"[❌ Erro: {e}]", True)


def get_language_from_extension(nome):
    ext = os.path.splitext(nome)[1].lower().lstrip('.')
    mapa = {
        'py': 'python', 'pyw': 'python', 'pyi': 'python',
        'js': 'javascript', 'jsx': 'jsx', 'mjs': 'javascript', 'cjs': 'javascript',
        'ts': 'typescript', 'tsx': 'tsx', 'vue': 'vue', 'svelte': 'svelte',
        'html': 'html', 'htm': 'html', 'xhtml': 'html',
        'css': 'css', 'scss': 'scss', 'sass': 'sass', 'less': 'less',
        'json': 'json', 'json5': 'json5', 'hjson': 'hjson',
        'yaml': 'yaml', 'yml': 'yaml', 'toml': 'toml',
        'md': 'markdown', 'markdown': 'markdown', 'rst': 'rst',
        'sh': 'bash', 'bash': 'bash', 'zsh': 'bash', 'fish': 'fish',
        'rb': 'ruby', 'go': 'go', 'rs': 'rust',
        'java': 'java', 'kt': 'kotlin', 'scala': 'scala',
        'c': 'c', 'h': 'c', 'cpp': 'cpp', 'cc': 'cpp', 'cxx': 'cpp',
        'hpp': 'cpp', 'hh': 'cpp', 'hxx': 'cpp',
        'cs': 'csharp', 'swift': 'swift', 'php': 'php',
        'sql': 'sql', 'r': 'r', 'jl': 'julia',
        'lua': 'lua', 'pl': 'perl', 'pm': 'perl',
        'tex': 'latex', 'bib': 'bibtex',
        'xml': 'xml', 'svg': 'xml',
        'ini': 'ini', 'cfg': 'ini', 'conf': 'ini', 'config': 'ini',
        'properties': 'properties', 'ipynb': 'json',
    }
    return mapa.get(ext, 'text')


# ============================================
# WRITER DE TRANSCRIÇÕES (modo separate)
# ============================================

def _sanitize(logical, max_len=MAX_TRANSCRIPTION_FILENAME):
    temp = logical.replace('::', '\x00').replace('/', '\x00').replace('\\', '\x00')
    temp = temp.replace(' ', '_')
    parts = temp.split('\x00')
    limpos = []
    for p in parts:
        p = ''.join(c if (c.isalnum() or c in '.-_') else '_' for c in p)
        p = p.strip('._') or '_'
        limpos.append(p)
    s = '__'.join(limpos)
    if len(s) > max_len:
        ext = os.path.splitext(s)[1]
        ext_len = len(ext)
        manter = max_len - ext_len - 3
        if manter < 10:
            s = s[:max_len]
        else:
            s = s[:manter] + '...' + ext
    return s or 'arquivo'


class TranscriptionWriter:
    def __init__(self, base_dir, rel_dir_name):
        self.base_dir = os.path.abspath(base_dir)
        self.rel_dir_name = rel_dir_name
        self._contador = 0
        self._usados = set()

    def garantir_dir(self):
        os.makedirs(self.base_dir, exist_ok=True)

    def escrever(self, nome_logico, conteudo):
        self._contador += 1
        base = _sanitize(nome_logico)
        candidato = base
        sufixo = 1
        while candidato in self._usados:
            stem, ext = os.path.splitext(base)
            candidato = f"{stem}-{sufixo}{ext}"
            sufixo += 1
        self._usados.add(candidato)
        nome_arquivo = f"{self._contador:04d}__{candidato}.md"
        caminho = os.path.join(self.base_dir, nome_arquivo)
        cabecalho = (f"<!-- Origem: {nome_logico} -->\n"
                     f"# `{nome_logico}`\n\n")
        lang = get_language_from_extension(nome_logico)
        corpo = f"```{lang}\n{conteudo}\n```\n"
        try:
            with open(caminho, 'w', encoding='utf-8') as f:
                f.write(cabecalho + corpo)
        except OSError:
            return None
        return f"{self.rel_dir_name}/{nome_arquivo}"


# ============================================
# ÁRVORE DE MEMBROS
# ============================================

def _build_archive_tree(entradas):
    tree = {}
    for nome, tamanho, is_dir in entradas:
        partes = [p for p in nome.strip('/').split('/') if p]
        if not partes:
            continue
        node = tree
        for p in partes[:-1]:
            if not isinstance(node.get(p), dict):
                node[p] = {}
            node = node[p]
        ultimo = partes[-1]
        if is_dir or nome.endswith('/'):
            if not isinstance(node.get(ultimo), dict):
                node[ultimo] = {}
        else:
            node[ultimo] = (tamanho,)
    return tree


def _render_archive_tree(tree, prefix):
    linhas = []

    def render(node, pref):
        itens = list(node.keys())
        pastas = [k for k in itens if isinstance(node[k], dict)]
        arquivos = [k for k in itens if isinstance(node[k], tuple)]
        pastas.sort(key=str.lower)
        arquivos.sort(key=str.lower)
        ordenados = pastas + arquivos
        for i, k in enumerate(ordenados):
            ultimo = (i == len(ordenados) - 1)
            conector = "└── " if ultimo else "├── "
            nome_md = escape_md(k)
            valor = node[k]
            if isinstance(valor, dict):
                linhas.append(f"{pref}{conector}📁 {nome_md}/")
                render(valor, pref + ("    " if ultimo else "│   "))
            else:
                tam = valor[0] if valor else 0
                linesz = _formata_tamanho(tam) if tam >= 0 else '?'
                linhas.append(f"{pref}{conector}📄 {nome_md} ({linesz})")

    render(tree, prefix)
    return linhas


# ============================================
# PROCESSAMENTO RECURSIVO
# ============================================

def _processar_archive_recursivo(
        source, nome_original, chain, prefix, depth,
        archive_mode, archive_recurse, archive_max_depth,
        max_lines, max_file_size, writer, stats, lines):

    handler = REGISTRY.escolher(source, nome_original)
    if handler is None:
        lines.append(f"{prefix}└── ⚠️ Formato não reconhecido")
        stats['errors'] += 1
        return
    if not handler.disponivel():
        lines.append(f"{prefix}└── ⚠️ Precisa de ferramenta externa "
                     f"({handler.nome}) — não instalada")
        stats['errors'] += 1
        return

    try:
        entradas = handler.listar(source)
    except Exception as e:
        lines.append(f"{prefix}└── ❌ Falha ao ler: {e}")
        stats['errors'] += 1
        return

    stats['archive_members'] += len(entradas)
    tree = _build_archive_tree(entradas)
    lines.extend(_render_archive_tree(tree, prefix))

    if archive_mode != 'content':
        return

    total_lido = 0
    for nome, tamanho, is_dir in entradas:
        if is_dir:
            continue
        try:
            dados = handler.ler(source, nome)
        except Exception:
            dados = None
        if not dados:
            continue
        nested_fmt = detectar_formato_por_magic(io.BytesIO(dados)) or \
                     detectar_formato(io.BytesIO(dados), nome)
        if nested_fmt and archive_recurse and depth < archive_max_depth:
            novo_pref = prefix + "    "
            lines.append(f"{novo_pref}🗜️ Conteúdo de `{escape_md(nome)}` "
                         f"(nível {depth + 1}, {nested_fmt}):")
            _processar_archive_recursivo(
                io.BytesIO(dados), nome, chain + [nome], novo_pref + "    ",
                depth + 1, archive_mode, archive_recurse, archive_max_depth,
                max_lines, max_file_size, writer, stats, lines)
            continue

        ext = os.path.splitext(nome)[1].lower()
        if ext not in TEXT_EXTENSIONS and b'\0' in dados[:2048]:
            continue
        if tamanho > max_file_size and tamanho >= 0:
            continue
        if total_lido + len(dados) > MAX_ARCHIVE_TOTAL_BYTES:
            lines.append(f"{prefix}    ⚠️ Limite total de leitura atingido")
            break

        texto = None
        for enc in ('utf-8', 'latin-1', 'cp1252', 'iso-8859-1'):
            try:
                texto = dados.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        if texto is None:
            continue
        if max_lines:
            todas = texto.splitlines()
            if len(todas) > max_lines:
                texto = ('\n'.join(todas[:max_lines])
                         + f"\n... (continuação, {max_lines} linhas mostradas)")

        logical = "::".join(chain + [nome])
        if writer is not None:
            caminho = writer.escrever(logical, texto)
            if caminho:
                stats['archive_files'] += 1
                lines.append(f"{prefix}    📝 Texto de `{escape_md(nome)}` → "
                             f"[ver]({caminho})")
        else:
            lang = get_language_from_extension(nome)
            lines.append(f"{prefix}    📝 `{escape_md(nome)}`:")
            lines.append(f"{prefix}    ```{lang}")
            for ln in texto.split('\n'):
                lines.append(f"{prefix}    {ln}")
            lines.append(f"{prefix}    ```")
            stats['archive_files'] += 1
        total_lido += len(dados)


# ============================================
# MODO: APENAS ÁRVORE
# ============================================

def generate_tree_only(start_dir, output_file, max_depth=None,
                       include_hidden=False, path_filter=None):
    start_dir = os.path.abspath(start_dir)
    if not os.path.isdir(start_dir):
        print_error(f"Diretório inválido: {start_dir}")
        return False
    if path_filter is None:
        path_filter = PathFilter(start_dir)
    abs_output = os.path.abspath(output_file)
    stats = {'dirs': 0, 'files': 0}
    lines = []
    dir_name = os.path.basename(start_dir) or start_dir
    agora = _agora()

    lines.append(f"# 📂 Estrutura de Diretórios: `{dir_name}`\n")
    lines.append(f"**Diretório raiz:** `{start_dir}`\n")
    lines.append(f"**Data:** {agora}\n")
    lines.append("**Modo:** Apenas estrutura\n")
    lines.append("---\n")

    visited = set()

    def walk(d, prefix="", depth=0):
        nonlocal stats
        if max_depth is not None and depth > max_depth:
            return
        real = os.path.realpath(d)
        if real in visited:
            lines.append(f"{prefix}└── 🔗 (link circular — não expandido)")
            return
        visited.add(real)
        try:
            itens = sorted(os.listdir(d))
            if not include_hidden:
                itens = [i for i in itens if not i.startswith('.')]
            dirs, files = [], []
            for it in itens:
                full = os.path.join(d, it)
                if os.path.abspath(full) == abs_output:
                    continue
                if not path_filter.permitido(full):
                    continue
                (dirs if os.path.isdir(full) else files).append(it)
            ordenados = dirs + files
            for i, it in enumerate(ordenados):
                ultimo = (i == len(ordenados) - 1)
                full = os.path.join(d, it)
                conector = "└── " if ultimo else "├── "
                nome_md = escape_md(it)
                if os.path.isdir(full):
                    lines.append(f"{prefix}{conector}📁 {nome_md}/")
                    stats['dirs'] += 1
                    walk(full, prefix + ("    " if ultimo else "│   "), depth + 1)
                else:
                    stats['files'] += 1
                    lines.append(f"{prefix}{conector}📄 {nome_md}")
        except PermissionError:
            lines.append(f"{prefix}└── ⚠️ Sem permissão")
        except OSError as e:
            lines.append(f"{prefix}└── ❌ Erro: {e}")

    lines.append("## 🌳 Árvore de Diretórios\n")
    lines.append("```")
    lines.append(f"{dir_name}/")
    walk(start_dir)
    lines.append("```\n")
    lines.append("---\n")
    lines.append("## 📊 Estatísticas\n")
    lines.append(f"- 📁 Subpastas: {stats['dirs']}")
    lines.append(f"- 📄 Arquivos: {stats['files']}\n")
    lines.append("---\n")
    lines.append(f"*Gerado em {agora}*")

    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
        print_success(f"Gerado: {output_file}")
        return True
    except OSError as e:
        print_error(f"Erro: {e}")
        return False


# ============================================
# GERAÇÃO PRINCIPAL
# ============================================

def generate_tree_with_content(
        start_dir, output_file,
        max_depth=None, max_file_lines=None, include_hidden=False,
        root_only=False, max_file_size=MAX_FILE_SIZE,
        archive_mode='skip',
        archive_recurse=False, archive_max_depth=MAX_ARCHIVE_DEPTH,
        output_mode='inline', transcriptions_dir=None, path_filter=None):

    start_dir = os.path.abspath(start_dir)
    if not os.path.isdir(start_dir):
        print_error(f"Diretório inválido: {start_dir}")
        return False
    if path_filter is None:
        path_filter = PathFilter(start_dir)

    abs_output = os.path.abspath(output_file)
    out_dir = os.path.dirname(abs_output)
    stem = os.path.splitext(os.path.basename(abs_output))[0]

    writer = None
    rel_dir_name = None
    if output_mode == 'separate':
        if transcriptions_dir:
            trans_dir = os.path.abspath(transcriptions_dir)
            rel_dir_name = os.path.relpath(trans_dir, out_dir)
        else:
            trans_dir = os.path.join(out_dir, f"{stem}_arquivos")
            rel_dir_name = f"{stem}_arquivos"
        writer = TranscriptionWriter(trans_dir, rel_dir_name)
        try:
            writer.garantir_dir()
        except OSError as e:
            print_error(f"Não consegui criar {trans_dir}: {e}")
            return False

    stats = {
        'dirs': 0, 'files': 0, 'text_files': 0, 'transcribed': 0,
        'skipped': 0, 'errors': 0,
        'archives': 0, 'archive_members': 0, 'archive_files': 0,
    }
    lines = []
    dir_name = os.path.basename(start_dir) or start_dir
    agora = _agora()

    lines.append(f"# 📂 Estrutura e Conteúdo: `{dir_name}`\n")
    lines.append(f"**Diretório raiz:** `{start_dir}`\n")
    lines.append(f"**Data:** {agora}\n")
    if root_only:
        lines.append("**⚠️ Modo:** apenas arquivos da raiz transcritos\n")
    if archive_mode != 'skip':
        rot = {'list': "apenas listar conteúdo",
               'content': "listar E transcrever"}[archive_mode]
        rec = " (recursivo)" if archive_recurse else ""
        lines.append(f"**🗜️ Containers:** {rot}{rec}\n")
    if output_mode == 'separate':
        lines.append(f"**📁 Transcrições em:** `{rel_dir_name}/`\n")
    lines.append("---\n")

    visited = set()

    def walk(d, prefix="", depth=0, is_root=True):
        nonlocal stats
        if max_depth is not None and depth > max_depth:
            return
        real = os.path.realpath(d)
        if real in visited:
            lines.append(f"{prefix}└── 🔗 **(link circular)**")
            return
        visited.add(real)
        try:
            itens = sorted(os.listdir(d))
            if not include_hidden:
                itens = [i for i in itens if not i.startswith('.')]
            dirs, files = [], []
            for it in itens:
                full = os.path.join(d, it)
                if os.path.abspath(full) == abs_output:
                    continue
                if not path_filter.permitido(full):
                    continue
                (dirs if os.path.isdir(full) else files).append(it)
            ordenados = dirs + files
            for i, it in enumerate(ordenados):
                ultimo = (i == len(ordenados) - 1)
                full = os.path.join(d, it)
                conector = "└── " if ultimo else "├── "
                nome_md = escape_md(it)
                novo_prefix = prefix + ("    " if ultimo else "│   ")

                if os.path.isdir(full):
                    lines.append(f"{prefix}{conector}📁 **{nome_md}/**")
                    stats['dirs'] += 1
                    walk(full, novo_prefix, depth + 1, False)
                    continue

                stats['files'] += 1
                try:
                    size = os.path.getsize(full)
                except OSError:
                    size = 0
                size_str = f" ({_formata_tamanho(size)})"

                fmt = detectar_formato(full)
                if fmt and archive_mode != 'skip':
                    handler = REGISTRY.escolher(full, it)
                    if handler is None:
                        fmt = None
                    elif not handler.disponivel():
                        lines.append(f"{prefix}{conector}🗜️ **{nome_md}**{size_str} "
                                     f"— requer {handler.nome} (não instalado)")
                        stats['skipped'] += 1
                        continue
                    else:
                        stats['archives'] += 1
                        lines.append(f"{prefix}{conector}🗜️ **{nome_md}**"
                                     f"{size_str} ({fmt})")
                        if size > MAX_ARCHIVE_SIZE:
                            lines.append(f"{novo_prefix}└── ⚠️ Grande demais")
                            continue
                        _processar_archive_recursivo(
                            full, it, [it], novo_prefix, 0,
                            archive_mode, archive_recurse, archive_max_depth,
                            max_file_lines, max_file_size, writer, stats, lines)
                        continue

                is_txt = is_text_file(full)
                deve = is_txt and (is_root or not root_only)
                if deve:
                    stats['text_files'] += 1
                    stats['transcribed'] += 1
                    conteudo, erro = get_file_content(full, max_file_lines,
                                                      max_file_size)
                    if erro:
                        lines.append(f"{prefix}{conector}📄 **{nome_md}**"
                                     f"{size_str} — ⚠️")
                        lines.append(f"{prefix}    > {conteudo}")
                    elif writer is not None:
                        caminho = writer.escrever(it, conteudo)
                        if caminho:
                            lines.append(f"{prefix}{conector}📄 **{nome_md}**"
                                         f"{size_str} → [ver]({caminho})")
                        else:
                            lines.append(f"{prefix}{conector}📄 **{nome_md}**"
                                         f"{size_str} — ⚠️ falha ao salvar")
                    else:
                        lines.append(f"{prefix}{conector}📄 **{nome_md}**{size_str}")
                        lang = get_language_from_extension(it)
                        lines.append(f"{prefix}    ```{lang}")
                        lines.append(conteudo)
                        lines.append(f"{prefix}    ```")
                    lines.append("")
                elif is_txt:
                    stats['text_files'] += 1
                    if not is_root and root_only:
                        lines.append(f"{prefix}{conector}📄 **{nome_md}**"
                                     f"{size_str} (não transcrito — subpasta)")
                    else:
                        lines.append(f"{prefix}{conector}📄 **{nome_md}**"
                                     f"{size_str} (não transcrito)")
                else:
                    stats['skipped'] += 1
                    lines.append(f"{prefix}{conector}📎 **{nome_md}**"
                                 f"{size_str} (não-texto)")
        except PermissionError:
            lines.append(f"{prefix}└── ⚠️ **Sem permissão**")
            stats['errors'] += 1
        except OSError as e:
            lines.append(f"{prefix}└── ❌ **Erro:** {e}")
            stats['errors'] += 1

    lines.append("## 🌳 Estrutura de Diretórios\n")
    lines.append("```")
    lines.append(f"{dir_name}/")
    walk(start_dir)
    lines.append("```\n")
    lines.append("---\n")
    lines.append("## 📊 Estatísticas\n")
    lines.append(f"- 📁 Subpastas: {stats['dirs']}")
    lines.append(f"- 📄 Arquivos totais: {stats['files']}")
    lines.append(f"- 📝 Texto encontrados: {stats['text_files']}")
    lines.append(f"- 📝 Transcritos: {stats['transcribed']}")
    if stats['archives']:
        lines.append(f"- 🗜️ Containers processados: {stats['archives']}")
        lines.append(f"- 🗜️ Membros listados: {stats['archive_members']}")
        if archive_mode == 'content':
            lines.append(f"- 🗜️ Membros de texto transcritos: "
                         f"{stats['archive_files']}")
    lines.append(f"- ⏭️ Ignorados (não-texto): {stats['skipped']}")
    if stats['errors']:
        lines.append(f"- ❌ Erros: {stats['errors']}")
    if output_mode == 'separate':
        lines.append(f"- 📁 Transcrições em: `{rel_dir_name}/`")
    lines.append("")

    lines.append("---\n")
    lines.append("## 📌 Legenda\n")
    lines.append("- 📁 Pasta")
    lines.append("- 📄 Arquivo de texto")
    lines.append("- 📎 Arquivo binário")
    lines.append("- 🗜️ Container (zip, tar, img, deb, iso, boot, sparse, disk, ...)")
    lines.append("- 🔗 Link circular (não expandido)")
    lines.append("")
    lines.append("---\n")
    lines.append(f"*Gerado em {agora}*")

    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))
    except OSError as e:
        print_error(f"Erro ao escrever: {e}")
        return False
    print_success(f"Gerado: {output_file}")
    print(f"📊 Subpastas: {stats['dirs']} · Arquivos: {stats['files']} · "
          f"Transcritos: {stats['transcribed']}")
    if stats['archives']:
        print(f"   🗜️ {stats['archives']} container(s), "
              f"{stats['archive_members']} membro(s)")
    if output_mode == 'separate':
        print(f"   📁 Transcrições em: {writer.base_dir}")
    print(f"📂 {os.path.abspath(output_file)}")
    return True


# ============================================
# UI
# ============================================

def _mostrar_diagnostico():
    print_info("Ferramentas detectadas (o que cada formato pode processar):")
    for nome, status in resumo_ferramentas():
        print(f"   {nome:<16} {status}")
    print()


def _perguntar_archive():
    print_info("\nPasso 8: Containers (zip, tar, img, deb, iso, apk, boot, sparse, ...)")
    print("   [1] Ignorar (só aparecem como binário)")
    print("   [2] Apenas listar o conteúdo")
    print("   [3] Listar E transcrever os textos internos")
    op = get_input("Escolha", default="1", valid_options=["1", "2", "3"])
    if op == "1":
        print_success("Containers: ignorados")
        return ('skip', False, MAX_ARCHIVE_DEPTH, 'inline', None)

    archive_mode = 'list' if op == "2" else 'content'
    print_success("Containers: " + ("listar" if archive_mode == 'list'
                                     else "listar e transcrever"))

    rec = get_input("Recursar em containers dentro de containers?",
                    default=False, input_type=bool)
    max_depth = MAX_ARCHIVE_DEPTH
    if rec:
        di = get_input(f"Profundidade máxima [{MAX_ARCHIVE_DEPTH}]",
                       default=MAX_ARCHIVE_DEPTH)
        try:
            max_depth = max(1, int(di))
        except ValueError:
            max_depth = MAX_ARCHIVE_DEPTH
        print_success(f"Recursão até {max_depth} nível(is)")
    else:
        print_success("Sem recursão")

    output_mode = 'inline'
    trans_dir = None
    if archive_mode == 'content':
        print("\n   Como salvar as transcrições?")
        print("   [1] Inline — tudo no .md principal")
        print("   [2] Separado — .md + pasta de arquivos")
        o = get_input("Escolha", default="1", valid_options=["1", "2"])
        if o == "2":
            output_mode = 'separate'
            nome = get_input("Nome da pasta de transcrições (Enter = padrão)",
                             default="")
            trans_dir = nome or None
            print_success("Transcrições em arquivos separados")
        else:
            print_success("Transcrições inline")
    return (archive_mode, rec, max_depth, output_mode, trans_dir)


def _executar_uma_vez():
    _mostrar_diagnostico()

    print_info("Passo 0: Modo de operação")
    print("   [1] Apenas Árvore")
    print("   [2] Árvore + Transcrição\n")
    modo = get_input("Escolha", default="2", valid_options=["1", "2"])
    modo_simples = (modo == "1")

    print_info("\nPasso 1: Diretório")
    start_dir = get_directory_path()
    print_success(f"Diretório: {start_dir}")

    print_info("\nPasso 2: Arquivo de saída")
    output_file = get_output_filename()
    print_success(f"Saída: {output_file}")

    print_info("\nPasso 3: Profundidade")
    di = get_input("Profundidade máxima (Enter = ilimitada)", default=None)
    max_depth = int(di) if di else None
    print_success(f"Profundidade: {max_depth or 'Ilimitada'}")

    print_info("\nPasso 4: Arquivos ocultos")
    include_hidden = get_input("Incluir ocultos?", default=False, input_type=bool)
    print_success("Sim" if include_hidden else "Não")

    max_lines = None
    max_size_mb = 5
    root_only = False
    archive_mode = 'skip'
    archive_recurse = False
    archive_max_depth = MAX_ARCHIVE_DEPTH
    output_mode = 'inline'
    trans_dir = None

    if not modo_simples:
        print_info("\nPasso 5: Limite de linhas por arquivo")
        li = get_input("Máximo de linhas (Enter = ilimitado)", default=None)
        max_lines = int(li) if li else None
        print_success(f"Linhas: {max_lines or 'Ilimitado'}")

        print_info("\nPasso 6: Modo de transcrição")
        print("   [s] TODOS os arquivos de texto")
        print("   [n] APENAS arquivos da PASTA RAIZ")
        root_only = get_input("Apenas raiz? (s = raiz, n = todos)",
                              default=False, input_type=bool)
        print_success("Apenas raiz" if root_only else "Todos")

        print_info("\nPasso 7: Tamanho máximo por arquivo (MB)")
        si = get_input("Máximo (MB)", default=5)
        try:
            max_size_mb = float(si)
            if max_size_mb <= 0:
                raise ValueError
        except ValueError:
            max_size_mb = 5
        print_success(f"{max_size_mb} MB")

        (archive_mode, archive_recurse, archive_max_depth,
         output_mode, trans_dir) = _perguntar_archive()

    print_header("📋 RESUMO")
    print(f"{Colors.BOLD}Modo:{Colors.END} "
          f"{'Apenas Árvore' if modo_simples else 'Árvore + Transcrição'}")
    print(f"{Colors.BOLD}Diretório:{Colors.END} {start_dir}")
    print(f"{Colors.BOLD}Saída:{Colors.END} {output_file}")
    print(f"{Colors.BOLD}Profundidade:{Colors.END} {max_depth or 'Ilimitada'}")
    print(f"{Colors.BOLD}Ocultos:{Colors.END} "
          f"{'Sim' if include_hidden else 'Não'}")
    if not modo_simples:
        print(f"{Colors.BOLD}Linhas:{Colors.END} {max_lines or 'Ilimitado'}")
        print(f"{Colors.BOLD}Transcrição:{Colors.END} "
              f"{'Apenas raiz' if root_only else 'Todos'}")
        print(f"{Colors.BOLD}Tamanho max:{Colors.END} {max_size_mb} MB")
        rot = {'skip': "ignorar",
               'list': "listar",
               'content': "listar + transcrever"}[archive_mode]
        print(f"{Colors.BOLD}Containers:{Colors.END} {rot}"
              f"{f' (recursivo até {archive_max_depth})' if archive_recurse else ''}")
        if archive_mode == 'content':
            print(f"{Colors.BOLD}Saída das transcrições:{Colors.END} "
                  f"{'inline' if output_mode == 'inline' else 'separado'}")

    print()
    if not get_input("🔄 Gerar com estas configurações?",
                     default=True, input_type=bool):
        print_warning("Cancelado.")
        return None

    print_header("🔄 GERANDO...")
    if modo_simples:
        return generate_tree_only(start_dir, output_file, max_depth,
                                  include_hidden)
    return generate_tree_with_content(
        start_dir, output_file, max_depth, max_lines, include_hidden,
        root_only, max_file_size=max_size_mb * 1024 * 1024,
        archive_mode=archive_mode,
        archive_recurse=archive_recurse,
        archive_max_depth=archive_max_depth,
        output_mode=output_mode,
        transcriptions_dir=trans_dir)


def main_interactive():
    os.system('cls' if os.name == 'nt' else 'clear')
    print_header("🌳 TREE CONTENT GENERATOR - INTERATIVO (v6)")
    print(f"{Colors.BOLD}Bem-vindo!{Colors.END}\n")
    try:
        while True:
            try:
                r = _executar_uma_vez()
            except UserCancelled as e:
                print_warning(str(e))
                break
            if r is True:
                print_header("✅ CONCLUÍDO")
            elif r is False:
                print_header("❌ FALHOU")
            print()
            if not get_input("🔄 Gerar outro arquivo?", default=False,
                             input_type=bool):
                break
    except UserCancelled:
        pass
    print("\n" + "=" * 60)
    print(f"{Colors.GREEN}👋 Obrigado!{Colors.END}")
    print("=" * 60 + "\n")


def _lista_csv(valores):
    """Aceita '--x a,b --x c' e devolve ['a', 'b', 'c']."""
    out = []
    for v in valores or []:
        out += [p.strip() for p in v.split(',') if p.strip()]
    return out


def build_arg_parser():
    ap = argparse.ArgumentParser(
        prog="geradordepastasearquivos.py",
        description="Gera um .md com a árvore e o conteúdo de uma pasta. "
                    "Sem argumentos, abre o modo interativo.")
    ap.add_argument("dir", help="Pasta a percorrer")
    ap.add_argument("-o", "--output", default="estrutura_completa.md",
                    help="Arquivo .md de saída (padrão: %(default)s)")
    ap.add_argument("--only", action="append", metavar="PASTAS",
                    help="Só inclui estes caminhos relativos (vírgula ou repetido)")
    ap.add_argument("--exclude", action="append", metavar="PADRÕES",
                    help="Padrões extras a ignorar (estilo .gitignore)")
    ap.add_argument("--no-default-excludes", action="store_true",
                    help="Não aplica a lista DEFAULT_EXCLUDES")
    ap.add_argument("--no-gitignore", action="store_true",
                    help="Não respeita o .gitignore da raiz")
    ap.add_argument("--hidden", action="store_true",
                    help="Inclui arquivos/pastas ocultos")
    ap.add_argument("--tree-only", action="store_true",
                    help="Só a árvore, sem conteúdo")
    ap.add_argument("--max-depth", type=int, default=None)
    ap.add_argument("--max-lines", type=int, default=None,
                    help="Máximo de linhas transcritas por arquivo")
    ap.add_argument("--max-size", type=float, default=5,
                    help="Tamanho máximo por arquivo, em MB (padrão: 5)")
    ap.add_argument("--archives", choices=["skip", "list", "content"],
                    default="skip", help="O que fazer com containers")
    ap.add_argument("--separate", action="store_true",
                    help="Transcrições em pasta separada em vez de inline")
    return ap


def main_cli(argv):
    a = build_arg_parser().parse_args(argv)
    filtro = PathFilter(
        a.dir, excludes=_lista_csv(a.exclude),
        use_defaults=not a.no_default_excludes,
        respect_gitignore=not a.no_gitignore,
        only=_lista_csv(a.only))
    if a.tree_only:
        ok = generate_tree_only(a.dir, a.output, a.max_depth, a.hidden,
                                path_filter=filtro)
    else:
        ok = generate_tree_with_content(
            a.dir, a.output, a.max_depth, a.max_lines, a.hidden,
            max_file_size=int(a.max_size * 1024 * 1024),
            archive_mode=a.archives,
            output_mode='separate' if a.separate else 'inline',
            path_filter=filtro)
    return 0 if ok else 1


if __name__ == "__main__":
    if len(sys.argv) > 1:
        sys.exit(main_cli(sys.argv[1:]))
    try:
        main_interactive()
    except KeyboardInterrupt:
        print("\n\nCancelado pelo usuário.\n")
        sys.exit(0)
    except Exception as e:
        print_error(f"Erro inesperado: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
