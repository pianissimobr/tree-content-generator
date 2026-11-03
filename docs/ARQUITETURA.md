# Arquitetura

Como o Tree Content Generator funciona por dentro.

---

## Visão geral

O gerador tem três camadas:

~~~
┌─────────────────────────────────────────────────────┐
│  UI interativa  (get_input, perguntas, resumo)      │
├─────────────────────────────────────────────────────┤
│  Orquestração   (generate_tree_with_content, walk)  │
├─────────────────────────────────────────────────────┤
│  Detecção       (detectar_formato, MAGIC, EXT_HINTS)│
├─────────────────────────────────────────────────────┤
│  Handlers       (ZipHandler, TarHandler, ...)       │
└─────────────────────────────────────────────────────┘
~~~

---

## 1. Detecção por magic bytes

`detectar_formato_por_magic(source)` lê os primeiros **32 KB + 1 byte** (32773
bytes) — cobre todas as assinaturas conhecidas, incluindo as que ficam em
offsets altos (`ustar` em 257, `EFI PART` em 512, `CD001` em 32769).

A tabela `MAGIC` casa `(offset, assinatura, nome_do_formato)`:

~~~python
MAGIC = [
    (0,     b"PK\x03\x04",    "zip"),
    (0,     b"\x1f\x8b",      "gzip"),
    (0,     b"ANDROID!",      "android-boot"),
    (257,   b"ustar",         "tar"),
    (512,   b"EFI PART",      "gpt"),
    (32769, b"CD001",         "iso"),
    (1080,  b"\x53\xef",      "ext"),
    # ...
]
~~~

A primeira assinatura que casa decide. Se nada casar, o **fallback** é pela
extensão (`EXT_HINTS`) e, para `.img`/`.bin` desconhecidos, pelo `file -b`.

Isso permite renomear `arquivo.zip` para `arquivo.xyz` que ele ainda abre, e
abrir `.docx` como zip sem handler específico.

---

## 2. Handler registry

Cada formato tem uma classe que herda de `Handler`:

~~~python
class Handler:
    nome = "?"
    nativo = True           # sem ferramenta externa?
    recursivo = True        # pode conter outros containers?

    def disponivel(self):   # ferramenta instalada?
        return True

    def listar(self, source):
        # Devolve [(nome, tamanho, is_dir), ...]
        raise NotImplementedError

    def ler(self, source, nome):
        # Devolve bytes do membro, ou None
        raise NotImplementedError
~~~

O `source` pode ser:

- **`str`** (caminho no filesystem) — quando o arquivo vem do disco
- **`io.BytesIO`** — quando é um membro de um container pai (aninhamento)

Handlers que só funcionam com caminho real (ex.: `debugfs`, `unsquashfs`)
chamam `_como_caminho(source)` — que escreve o `BytesIO` num tempfile e
devolve um `cleanup` para apagar depois.

### Handlers registrados

~~~
Nativos:      zip, tar, gzip, bzip2, xz, zstd, ar,
              android-boot, android-sparse, disk (MBR/GPT)
Externos:     7z, iso, squashfs, ext, fat
~~~

---

## 3. Processamento recursivo

`_processar_archive_recursivo()` é o coração. Para cada container:

~~~
1. Escolhe o handler via REGISTRY.escolher(source)
2. Se handler indisponível, marca e segue
3. Entradas = handler.listar(source)
4. Desenha a sub-árvore visual (pasta/arquivo)
5. Se archive_mode == "list": para aqui
6. Para cada membro:
   a. Lê os bytes via handler.ler(source, nome)
   b. Chama detectar_formato_por_magic(io.BytesIO(dados))
   c. Se é container E recursão ligada E depth < max_depth:
      recursa com _processar_archive_recursivo(BytesIO(dados), ...)
   d. Senão, se é texto: transcreve (inline ou writer)
~~~

### Guarda-corpos

- **`MAX_ARCHIVE_DEPTH`** (padrão 3) — evita recursão infinita
- **`MAX_ARCHIVE_MEMBERS`** (padrão 5000) — limita quantos membros listar
- **`MAX_ARCHIVE_TOTAL_BYTES`** (padrão 4 MB) — limita bytes lidos por archive
- **`MAX_ARCHIVE_SIZE`** (padrão 2 GB) — recusa arquivos absurdos
- **`MAX_FILE_SIZE`** (padrão 5 MB) — recusa membros de texto enormes

Todos ajustáveis nas constantes no topo do script.

---

## 3.1 Ignore (pastas padrão + .gitignore)

Antes de decidir se um item do `os.listdir()` entra na árvore,
`_item_ignorado()` é consultada. Ela combina três fontes, nessa ordem:

~~~
1. DEFAULT_IGNORE_DIRS / DEFAULT_IGNORE_FILES  (nome exato ou sufixo)
2. Regras de .gitignore acumuladas (raiz → subpasta atual)
3. Padrões extra informados pelo usuário (extra_ignore_patterns)
~~~

O `walk()` carrega o `.gitignore` de cada diretório que visita
(`_carregar_gitignore`) e acumula as regras ao descer — exatamente como o
git faz, com a simplificação de que não há meio-termo entre "regra bate" e
"não bate" por diretório intermediário (não cobre o caso raro de um
`.gitignore` filho tentar "designorar" algo que o pai baniu de forma
ambígua). Cada padrão de `.gitignore` é traduzido pra regex por
`_traduzir_padrao_gitignore()`, que entende `*`, `**`, `?`, `[...]`,
âncora (`/`) e sufixo de pasta (`/`).

Uma pasta ignorada aparece como uma linha só na árvore
(`(ignorado — padrão)` ou `(ignorado — .gitignore)`) e **não é percorrida**
— é isso que evita listar/ler os 50 mil arquivos de um `node_modules`.
Arquivos ignorados simplesmente não aparecem (silenciosos), só contam nas
estatísticas finais.

## 3.2 Ofuscação de segredos

Com `redact_secrets=True` (padrão), dois mecanismos agem antes de qualquer
conteúdo ir pro `.md`:

~~~
1. _eh_arquivo_sensivel(nome)       → .env, id_rsa, *.pem, credentials.json, ...
   Se bater: o conteúdo NUNCA é lido; vira um placeholder "🔒 sensível".
2. ofuscar_segredos(texto)          → roda SECRET_RULES sobre o texto lido
   Cada regra é (nome, regex, função_de_mascaramento); roda em sequência,
   soma quantos matches cada uma teve.
~~~

As duas camadas aplicam-se tanto ao `walk()` principal quanto ao conteúdo
lido de dentro de containers em `_processar_archive_recursivo()` — então um
`.env` dentro de um `.zip` é tratado do mesmo jeito que um `.env` solto no
disco. `SECRET_RULES` cobre chaves AWS/Google, tokens GitHub/Slack/Stripe,
JWT, blocos PEM de chave privada, credenciais em URL, cabeçalho
`Authorization: Bearer` e atribuições genéricas `CHAVE = valor` (com uma
lista de *placeholders* conhecidos — `os.environ`, `<exemplo>`, etc. — pra
não mascarar código que só *referencia* uma variável de ambiente).

## 4. Composição automática

O truque bonito: os handlers **compõem** sozinhos porque a recursão é genérica.
Um `.tgz` não precisa de handler especial:

~~~
backup.tgz
  -> magic: \x1f\x8b
GzipHandler.listar, devolve [("backup", -1, False)]
  -> processador recursivo lê "backup" via GzipHandler.ler
Bytes da tar descomprimida
  -> magic: ustar em offset 257
TarHandler.listar, devolve [("etc/", 0, True), ("etc/config", 512, False)]
  -> 
etc/config transcrito
~~~

O mesmo vale para:

- `.deb` -> ar -> data.tar.xz -> xz -> tar -> conteúdo
- `.img` sparse -> simg2img -> ext -> debugfs -> arquivo
- `.docx` -> zip -> word/document.xml

**Nenhum caso especial.** Só handlers que cooperam.

---

## 5. Modos de saída

### Inline (padrão)

Cada transcrição entra no `.md` principal dentro de um bloco de código.

~~~
arquivo main.py (2.1 KB)
  conteudo:
    def main(): ...
~~~

Vantagem: um arquivo só, fácil de mandar.
Desvantagem: pode ficar enorme.

### Separate

Cria uma pasta companheira (`<stem>_arquivos/`) e um arquivo por transcrição.
O `.md` principal ganha links.

~~~
arquivo main.py (2.1 KB) -> ver saida_arquivos/0001__main.py.md
~~~

Cada arquivo começa com um cabeçalho:

~~~markdown
<!-- Origem: main.py -->
# main.py

conteudo:
  def main(): ...
~~~

Vantagem: `.md` fica enxuto, fácil de versionar em partes.
Desvantagem: dois artefatos em vez de um.

---

## 6. Nome dos arquivos separados

`_sanitize()` transforma um nome lógico (que pode ter `/`, `::`, espaços) num
nome seguro para o sistema de arquivos:

| Lógico | Sanitizado |
|---|---|
| `core/engine.py` | `core__engine.py` |
| `firmware.zip::modem/README.txt` | `firmware.zip__modem__README.txt` |
| `arquivo com espaço e #símbolo.py` | `arquivo_com_espaco_e__símbolo.py` |

Colisões ganham sufixo `-1`, `-2`, etc. Nomes muito longos (>120 bytes) são
truncados pelo meio, preservando a extensão.

O `TranscriptionWriter` ainda prefixa com um contador (`0001__`, `0002__`)
para preservar a ordem.

---

## 7. Fluxo completo

~~~
main_interactive()
  -> _executar_uma_vez()          faz as perguntas
  -> generate_tree_with_content() orquestra
  -> walk()                       percorre o FS
       para cada arquivo:
         se é container:
           _processar_archive_recursivo()
             handler.listar()
             _render_archive_tree()
             para cada membro:
               handler.ler()
               detectar_formato_por_magic()
               recursa OU transcreve
         se é texto:
           get_file_content() -> inline OU writer.escrever()
  -> Escreve o .md final
~~~

---

## 8. Testes

`make test` carrega o `.py` como módulo e roda 16 checagens. Cada uma cria
arquivos temporários em `/tmp`, executa uma função e valida o resultado.

A ideia é ter uma rede de segurança rápida — se você alterar o `Registry` ou
`detectar_formato_por_magic`, os testes pegam regressões antes do commit.

---

## 9. Adicionar um novo handler

Três passos:

~~~python
# 1. Nova classe
class MeuHandler(Handler):
    nome, nativo, recursivo = "meu", True, True

    def listar(self, source):
        return [("a.txt", 100, False), ("pasta/", 0, True)]

    def ler(self, source, nome):
        return b"conteudo"

# 2. Assinatura no MAGIC (se tem magic próprio)
MAGIC.append((0, b"MEU\x00", "meu"))

# 3. Registrar
# Registry.__init__  -> adicionar MeuHandler na tupla
# Registry.escolher  -> adicionar rota para "meu" se precisar
~~~

Pronto. A recursão, o desenho da árvore, o escape, os guarda-corpos — tudo
funciona automaticamente.

