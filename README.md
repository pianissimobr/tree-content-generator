# 🌳 Tree Content Generator

**Um gerador de árvore de diretórios que abre o que está dentro.**

O Tree Content Generator percorre qualquer pasta e produz um arquivo Markdown com a
árvore de diretórios e — opcionalmente — o **conteúdo** de cada arquivo. Diferente
de ferramentas parecidas, ele não confia na extensão: **detecta o formato real por
magic bytes** e abre arquivos compactados, imagens de disco e imagens Android
diretamente, sem extrair nada no disco.

O resultado é um `.md` autocontido (ou um `.md` + pasta de transcrições) que você
pode mandar por e-mail, colar numa issue do GitHub, ou usar como contexto para uma
IA. Tudo em Python puro, com ferramentas externas opcionais para formatos exóticos.

---

## ✨ O que ele faz

- 📂 **Árvore de diretórios** com ícones, tamanhos e estatísticas
- 📝 **Transcrição de arquivos de texto** (com syntax highlighting apropriado)
- 🗜️ **Abre containers** — `.zip`, `.tar`, `.tar.gz`, `.deb`, `.apk`, `.7z`,
  `.iso`, `.img`, `.squashfs`, `.docx`, `.jar`, e mais
- 🎯 **Detecta o formato por magic bytes**, não por extensão — um `.docx` é
  reconhecido como zip, um `.img` é reconhecido como ext4/FAT/Android sparse
- 🔁 **Recursão em containers aninhados** — um `.tar.gz` dentro de um `.zip`
  dentro de um `.deb` é aberto até o fim, em memória, sem extrair nada
- 🎛️ **Três modos de container**: ignorar, apenas listar, ou listar e transcrever
- 🧩 **Saída inline ou separada** — tudo no `.md`, ou `.md` enxuto + pasta com um
  arquivo por transcrição
- 🛡️ **Não trava** — proteção contra symlinks circulares, sockets, FIFOs,
  arquivos corrompidos e arquivos grandes
- 🔍 **Diagnóstico inicial** — mostra quais ferramentas externas estão
  disponíveis antes de rodar
- ⏭️ **Ignora ruído por padrão** — `node_modules`, `__pycache__`, `.venv`,
  `dist`, `build`, `.git`, lockfiles e outras pastas/arquivos gerados
  automaticamente nunca entram na saída (é o que transforma um projeto
  "montado" de 500 MB–1 GB em 30 MB de código de verdade)
- 📝 **Respeita o `.gitignore`** do projeto (inclusive os aninhados em
  subpastas) e aceita padrões extras de exclusão (glob) informados por você
- 🔒 **Ofusca segredos automaticamente** — chaves de API, tokens, senhas,
  credenciais em URL e chaves privadas são substituídos por um marcador
  antes de ir pro `.md`; arquivos como `.env`, `id_rsa` e `*.pem` nunca têm
  o conteúdo transcrito

---

## 🚀 Uso rápido

~~~bash
# 1. Clone e entre na pasta
git clone https://github.com/SEU-USUARIO/tree-content-generator.git
cd tree-content-generator

# 2. Instale os opcionais (recomendado, mas não obrigatório)
make install

# 3. Confira o que ficou disponível
make check

# 4. Rode o gerador
make run
~~~

O programa é **interativo**. Ele pergunta:

1. Modo: só árvore, ou árvore + transcrição
2. Diretório
3. Nome do arquivo de saída
4. Profundidade máxima da árvore
5. Incluir arquivos ocultos?
6. **Ignorar pastas/arquivos** — padrão (node_modules, dist, venv, ...),
   `.gitignore` do projeto (se existir) e padrões extra
7. Limite de linhas por arquivo
8. Transcrever só a raiz ou tudo?
9. Tamanho máximo por arquivo
10. **Containers** — ignorar / listar / listar+transcrever, com recursão
11. Como salvar as transcrições — inline ou separado
12. **Ofuscar segredos** nos arquivos transcritos? (recomendado: sim)

A qualquer momento, digite `sair` para cancelar — nada é escrito antes da
confirmação final.

---

## 📋 Formatos suportados

| Formato | Nativo | Requer ferramenta | Transcreve? |
|---|:---:|:---:|:---:|
| `.zip`, `.jar`, `.apk`, `.docx`, `.xlsx`, `.odt`, `.epub` | ✅ | — | ✅ |
| `.tar`, `.tar.gz`, `.tgz`, `.tar.bz2`, `.tar.xz`, `.tar.zst` | ✅ | — | ✅ |
| `.gz`, `.bz2`, `.xz` (streams soltos) | ✅ | — | ✅ |
| `.zst` | ✅ (Python) | `zstandard` (pip) ou `zstd` | ✅ |
| `.deb`, `.a`, `.ar` | ✅ | — | ✅ |
| **Android boot image** (`ANDROID!`) | ✅ | — | ✅ |
| **MBR / GPT** (imagem particionada) | ✅ | — | ✅ (por partição) |
| **Android sparse image** | — | `simg2img` | ✅ |
| **ext2/3/4** (`.img`) | — | `debugfs` (`e2fsprogs`) | ✅ |
| **FAT12/16/32** (`.img`) | — | `mdir` (`mtools`) | ✅ |
| `.squashfs`, `.sqfs`, `.sfs` | — | `unsquashfs` | lista só |
| `.iso` | — | `isoinfo` **ou** `pycdlib` | lista só |
| `.7z` | — | `7z` **ou** `py7zr` | ✅ |
| `.rar` | — | `unrar` **ou** `7z` | ✅ |

A coluna "Nativo" indica que roda com a biblioteca padrão do Python. A coluna
"Requer ferramenta" mostra o binário ou pacote Python opcional. Se a ferramenta
não estiver instalada, o script apenas **ignora aquele arquivo** e continua —
nunca trava.

📖 Catálogo completo com exemplos: [`docs/FORMATOS.md`](docs/FORMATOS.md)

---

## ⏭️ Ignorando ruído (de 1 GB "montado" pra 30 MB de código)

Um projeto rodando localmente acumula `node_modules/`, `venv/`, caches de
build, binários compilados — nada disso é código, e nada disso deveria ir
pra uma análise de IA. Por padrão o gerador já corta isso:

- **Lista própria de pastas/arquivos gerados** — `node_modules`,
  `__pycache__`, `.venv`/`venv`, `dist`, `build`, `.next`, `target`,
  `.git`, `coverage`, `.idea`/`.vscode`, lockfiles (`package-lock.json`,
  `yarn.lock`, `Cargo.lock`, ...) e várias outras. A pasta aparece na árvore
  como uma linha só, marcada `(ignorado — padrão)`, sem ser percorrida —
  então um `node_modules` com 50 mil arquivos nem chega a ser listado.
- **`.gitignore` do projeto** — se existir um `.gitignore` na raiz (ou em
  subpastas), o gerador oferece respeitá-lo. Suporta o que normalmente se
  usa num `.gitignore`: comentários, negação (`!arquivo`), âncora
  (`/pasta`), pastas (`pasta/`), `*`, `**` e `?`. Não é uma reimplementação
  100% fiel do git — é uma heurística pensada pra esse caso de uso.
- **Padrões extra** — na hora de gerar, você pode informar padrões
  adicionais (`*.log, docs/rascunhos`) pra casos específicos do seu projeto.

Tudo isso pode ser desligado (útil se você quer ver exatamente o que o
`.gitignore` de um projeto está escondendo, por exemplo). Nas funções
Python, os parâmetros são `use_default_ignores`, `respect_gitignore` e
`extra_ignore_patterns`.

## 🔒 Ofuscando segredos antes de mandar pra uma IA

Mandar um projeto inteiro pra análise de uma IA de terceiros é exatamente o
tipo de situação em que uma chave de API esquecida num `config.py` vira um
vazamento. O modo "árvore + transcrição" ofusca isso por padrão:

- **Arquivos claramente sensíveis nunca são transcritos** — `.env` e
  variantes, `id_rsa`/`id_ed25519`, `*.pem`, `*.key`, `*.pfx`,
  `credentials.json`, `service-account.json` e outros aparecem como
  `🔒 Arquivo sensível — conteúdo não transcrito`, não importa o que tenha
  dentro.
- **O resto do texto passa por uma varredura de segredos** — chaves AWS
  (`AKIA...`), Google API Key, tokens do GitHub/Slack/Stripe, JWT, blocos
  `-----BEGIN PRIVATE KEY-----`, credenciais em URL (`user:senha@host`),
  cabeçalho `Authorization: Bearer ...` e atribuições do tipo
  `SENHA = "..."` / `API_KEY=...` são substituídos por um marcador como
  `«OCULTADO»` ou `«OCULTADO:AWS-KEY»`, mantendo o resto do arquivo intacto.
- O rodapé do `.md` mostra quantos segredos foram ofuscados e quantos
  arquivos sensíveis foram ocultados, pra você confirmar que nada vazou.

⚠️ **É uma heurística por regex, não uma garantia de segurança.** Revise a
saída antes de enviar pra terceiros, principalmente se o projeto tiver
segredos em formatos fora do comum. Pode ser desligado com
`redact_secrets=False` (não recomendado) se você já sabe que não há nada
sensível no projeto.

---

## 🎯 Por que ele existe

Ferramentas de árvore de diretórios geralmente fazem só duas coisas: listam nomes
ou despejam bytes como texto. Nenhuma das duas resolve o problema real de
**documentar um projeto que tem binários dentro** — firmware de dongle, pacotes
Android, imagens de disco, `.deb`.

O Tree Content Generator resolve isso tratando cada tipo de container como um
**filesystem virtual** que pode ser aberto, percorrido e transcrito — com um
handler específico por formato, detecção por magic bytes em vez de extensão, e
recursão natural entre eles.

O caso que originou o projeto: documentar o repositório do
[OpenDongle](https://github.com/pianissimobr/OpenDongle) — que tem `boot.bin` e
`rootfs.bin` (Android sparse images com ext4 dentro), `calibracao.tar` de 100 MB,
`.pyc`, `.jsonl` e logs. Sem esse suporte, a documentação ficaria cheia de
`📎 (binário)`.

---

## 🔧 Instalação

### Requisitos

- **Python 3.8+** (usa `io.BytesIO`, `struct`, `tarfile`, `zipfile`)
- **make** (opcional, mas simplifica tudo)
- Nenhuma dependência Python obrigatória

### Instalação completa (recomendado)

~~~bash
# 1. Ambiente virtual (isolado do sistema)
make venv

# 2. Pacotes Python (pycdlib, zstandard, py7zr, chardet)
make install-pip

# 3. Binários de sistema (7z, simg2img, debugfs, mdir, isoinfo, unsquashfs)
make install-sistema

# 4. Confira
make check
~~~

### Instalação mínima (sem opcionais)

Nada a fazer. O script já roda com `python3 geradordepastasearquivos.py` usando
apenas a biblioteca padrão. Você perde:

- `.7z`, `.rar` → sem `7z`/`py7zr`
- `.zst`, `.tzst` → sem `zstandard`/`zstd`
- `.iso` → sem `isoinfo`/`pycdlib`
- `.squashfs` → sem `unsquashfs`
- `.img` ext4 → sem `debugfs`
- `.img` FAT → sem `mdir`
- **Android sparse image** (crítico para o OpenDongle) → sem `simg2img`

Nada disso trava o script — só mostra `✗ instale: ...` no diagnóstico.

### Instalação manual (sem make)

~~~bash
# Python
pip install -r requirements.txt

# Sistema (Debian/Ubuntu/Mint)
sudo apt install p7zip-full simg2img e2fsprogs mtools \
                 genisoimage squashfs-tools file unrar-free

# Sistema (Fedora/RHEL)
sudo dnf install p7zip p7zip-plugins android-tools e2fsprogs \
                 mtools genisoimage squashfs-tools file unrar

# Sistema (Arch/Manjaro)
sudo pacman -S p7zip android-tools e2fsprogs mtools cdrtools \
               squashfs-tools file unrar
~~~

## 📖 Uso detalhado

### Modo "só árvore"

Rápido, nada é lido além dos nomes. Ideal para um overview de repositório grande.

~~~
├── 📁 src/
│   ├── 📄 main.py
│   └── 📄 utils.py
├── 📄 README.md
└── 📄 LICENSE
~~~

### Modo "árvore + transcrição" — inline

Tudo num só `.md`. Bom para colar numa issue ou mandar por e-mail.

~~~markdown
├── 📄 main.py (2.1 KB)
│   ```python
│   def main():
│       print("olá")
│   ```
~~~

### Modo "árvore + transcrição" — separado

O `.md` fica enxuto, com links; cada transcrição vira um arquivo à parte.

~~~markdown
├── 📄 main.py (2.1 KB) → [ver](saida_arquivos/0001__main.py.md)
~~~

E a pasta `saida_arquivos/`:

~~~
0001__main.py.md
0002__core__engine.py.md
0003__firmware.zip::modem__config.json.md
~~~

O `::` indica "dentro do archive" — fica óbvio de onde cada transcrição veio.

### Containers aninhados

O truque que faz tudo funcionar: os handlers **compõem sozinhos**. Um `boot.bin`
do OpenDongle passa por três níveis automaticamente:

~~~
boot.bin
  ↓ magic: \x3a\xff\x26\xed
Android sparse image
  ↓ simg2img → ext4
ext2/3/4
  ↓ debugfs
/extlinux/extlinux.conf
  ↓ transcrito!
~~~

A saída no `.md`:

~~~
├── 🗜️ **boot.bin** (12.4 MB) (android-sparse)
│   └── 🗜️ Conteúdo de `imagem-raw.img` (nível 1, ext):
│       ├── 📁 extlinux/
│       │   └── 📄 extlinux.conf (312 B)
│       │       ```text
│       │       DEFAULT primary
│       │       FDT /dtbs/qcom/msm8916-yiming-uz801v3.dtb
│       │       ```
│       └── 📄 Image.gz (8.2 MB)
~~~

---

## 🎛️ Makefile — todos os alvos

~~~
make help              Mostra esta lista
make install           pip + sistema
make install-pip       Só Python
make install-sistema   Só binários de sistema
make check             Diagnóstico do ambiente
make test              Testes de fumaça (16 checagens)
make run               Executa o gerador interativo
make venv              Cria .venv/
make venv-shell        Abre shell dentro do .venv
make clean             Remove caches e saída gerada
make uninstall         Remove pacotes Python do projeto
~~~

Variáveis configuráveis:

~~~bash
make PYTHON=python3.12 install-pip
make VENV_DIR=.venv-tcg venv
~~~

---

## 🏗️ Arquitetura

Dois conceitos bastam para entender tudo:

**1. Detecção por magic bytes.** A função `detectar_formato_por_magic()` lê os
primeiros 32 KB e casa contra uma tabela de assinaturas conhecidas (`PK\x03\x04`
= zip, `\x1f\x8b` = gzip, `ANDROID!` = boot image, `EFI PART` em offset 512 = GPT,
etc.). Extensão serve como fallback.

**2. Handler registry.** Cada formato tem um handler que implementa:

~~~python
class Handler:
    nome = 'zip'
    def disponivel(self):           # ferramenta instalada?
    def listar(self, source):        # [(nome, tamanho, is_dir), ...]
    def ler(self, source, nome):     # bytes do membro
~~~

O processador recursivo chama `listar()`, monta a árvore visual, e — para cada
membro — pergunta ao `detectar_formato_por_magic()` se aquele membro também é um
container. Se for, recursa com o handler apropriado. Nada é extraído em disco:
tudo trafega via `io.BytesIO`.

📖 Explicação completa: [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md)

---

## 🧪 Testes

~~~bash
make test
~~~

Roda 21 checagens de fumaça que criam arquivos temporários em `/tmp` e validam:

- Detecção por magic bytes de `zip`, `gzip`, `tar`, `tgz`, `android-boot`
- `ZipHandler` e `TarHandler` listam e leem corretamente
- `Registry.escolher` escolhe o handler certo por magic
- MBR falso (`55 AA` em 510) é reconhecido como disco
- Symlink circular não trava a geração
- Escape de Markdown funciona
- `valid_options` rejeita entrada fora da lista
- Modos `inline` e `separate` geram a saída correta
- Pastas padrão (`node_modules`) são ignoradas e não percorridas
- `.gitignore` do projeto é respeitado quando pedido
- Padrões extra de exclusão funcionam
- Chave da AWS hardcoded no código é ofuscada na transcrição
- Arquivo `.env` nunca tem o conteúdo transcrito

Tudo em `/tmp`, apagado no `finally`. Se algum teste falhar, ele é nomeado
explicitamente.

---

## 🐛 Problemas comuns

### "pip: externally-managed-environment"

Debian 12+ e Ubuntu 24+ bloqueiam `pip install` fora de venv. Duas saídas:

~~~bash
make venv && make install-pip       # recomendado
# ou
pip install --break-system-packages -r requirements.txt
~~~

### "simg2img não encontrado"

O `simg2img` não vem em todos os repositórios com esse nome. No Debian trixie:

~~~bash
sudo apt install simg2img
# se não achar, procure por:
apt search sparse | grep -i android
~~~

Sem ele, `boot.bin` e `rootfs.bin` (Android sparse) não abrem.

### Arquivo gerado fica gigante

Se um `.zip` tem 500 `.py` e você escolheu transcrever, o `.md` pode ficar com
MB. Use o **modo separado** — o `.md` principal continua pequeno e cada
transcrição vira seu próprio arquivo.

Ajuste também `MAX_ARCHIVE_TOTAL_BYTES` no início do script (padrão: 4 MB por
container).

### `.img` abre só como "não-texto"

Provavelmente é uma **imagem particionada** (MBR/GPT) que o parser não reconheceu,
ou é um formato exótico (ex.: UDF). O script cai no fallback `file -b` — se mesmo
isso não identificar, marca como binário.

Para investigar:

~~~bash
file disco.img
fdisk -l disco.img
~~~

### Quero só ver o que tem dentro de um `.tar` sem varrer o FS

Use o modo **list-only** (opção 2 no passo 8). Ele mostra a árvore interna sem
ler bytes. Perfeito para o `calibracao.tar` de 100 MB.

---

## 🛠️ Desenvolvimento

### Estrutura

~~~
.
├── Makefile
├── requirements.txt
├── instalar_opcionais.sh
├── geradordepastasearquivos.py    ← arquivo principal (v7)
├── docs/
│   ├── FORMATOS.md
│   └── ARQUITETURA.md
├── exemplos/
│   └── saida-exemplo.md
└── tests/
    └── testes_smoke.py
~~~

### Adicionar suporte a um novo formato

1. Crie uma classe que herde de `Handler`, implemente `listar()` e `ler()`.
2. Adicione a assinatura em `MAGIC` (se o formato tem magic próprio).
3. Registre a classe em `Registry.__init__`.

Exemplo para um formato hipotético `.xyz` com magic `XYZ`:

~~~python
class XyzHandler(Handler):
    nome, nativo, recursivo = 'xyz', True, True

    def listar(self, source):
        # devolve [(nome, tamanho, is_dir), ...]
        ...

    def ler(self, source, nome):
        # devolve bytes do membro 'nome', ou None
        ...
~~~

Depois:

~~~python
MAGIC.append((0, b'XYZ', 'xyz'))
# e em Registry.__init__:
for cls in (..., XyzHandler):
~~~

### Rodar os testes antes de commitar

~~~bash
make test && make clean
~~~

---

## 📜 Licença

MIT — veja [LICENSE](LICENSE).

Você pode usar, modificar, redistribuir e vender sem restrição, mantendo o aviso
de copyright original.

---

## 👤 Autor

Feito por **[@pianissimobr](https://github.com/pianissimobr)** — reaproveitamento
de hardware, documentação de projeto e inclusão digital. 🇧🇷

---

## 🙏 Créditos

- **`file(1)` magic database** — referência para as assinaturas de magic bytes
- **`tarfile`, `zipfile`, `gzip`, `bz2`, `lzma`** — biblioteca padrão do Python
- **`pycdlib`** (por Chris Lalancette) — leitura de ISO em Python puro
- **`zstandard`** (por Gregory Szorc) — bindings Python para libzstd
- **`py7zr`** (por Hiroshi Miura) — leitura de `.7z` em Python puro
- **`simg2img`** (Android Open Source Project) — conversão de sparse images

> Este projeto nasceu de uma pergunta simples: e se a gente pudesse mandar um
> projeto inteiro — com firmware, binários e tudo — como um único arquivo de
> texto?

