# Formatos suportados

Catálogo completo do que o Tree Content Generator consegue abrir, com
exemplos de saída.

---

## 🟢 Nativos (biblioteca padrão do Python)

### ZIP e primos

Detectado por magic `PK\x03\x04`, `PK\x05\x06` ou `PK\x07\x08`. A extensão não
importa — `.zip`, `.jar`, `.apk`, `.docx`, `.xlsx`, `.pptx`, `.odt`, `.epub`,
`.whl`, `.xpi`, `.crx`, `.ipa`, `.cbz`, `.nupkg` são **todos zip** e todos abrem.

~~~
├── 🗜️ **app.apk** (8.2 MB) (zip)
│   ├── 📁 META-INF/
│   │   ├── 📄 MANIFEST.MF (1.5 KB)
│   │   └── 📄 CERT.RSA (1.2 KB)
│   ├── 📄 AndroidManifest.xml (12 KB)     ← binário (AXML)
│   ├── 📄 classes.dex (4.8 MB)            ← binário (Dalvik)
│   └── 📄 resources.arsc (256 KB)         ← binário
~~~

`MANIFEST.MF` é transcrito; `AndroidManifest.xml` não (é XML binário).

### TAR e variações

Detectado por magic `ustar` em offset 257. Aceita `.tar`, `.tar.gz`, `.tgz`,
`.tar.bz2`, `.tar.xz`, `.tar.zst`, `.crate`, `.gem`, `.ipk`.

### Streams soltos

`.gz`, `.bz2`, `.xz` como streams sem tar dentro. Aparecem como um único membro
virtual cujo nome perde o sufixo:

~~~
├── 🗜️ **backup.gz** (1.2 MB) (gzip)
│   └── 📄 backup (5.4 MB)
~~~

### `ar` e `.deb`

Magic `!<arch>\n`. Debian packages abrem **em cascata**:

~~~
├── 🗜️ **pacote.deb** (4.2 MB) (ar)
│   ├── 📄 debian-binary (4 B)
│   ├── 📄 control.tar.gz (1.2 KB)
│   └── 📄 data.tar.xz (3.8 MB)
~~~

Com recursão ligada, `data.tar.xz` é aberto (xz → tar) e mostra o filesystem:

~~~
│   └── 🗜️ Conteúdo de `data.tar.xz` (nível 2, tar):
│       ├── 📁 usr/bin/
│       │   └── 📄 meu-programa (2.1 MB)
│       ├── 📁 etc/
│       │   └── 📄 meu-programa.conf (512 B)
│       └── 📁 usr/share/doc/
│           └── 📄 README (1.4 KB)     ← transcrito
~~~

### Android boot image

Magic `ANDROID!`. Estrutura:

~~~
[header] [kernel] [ramdisk] [second] [dtb]
~~~

Cada seção é um membro. O `ramdisk` tipicamente é `gzip(cpio)` — o handler de
gzip recursa nele e mostra o filesystem raiz do Android.

~~~
├── 🗜️ **boot.bin** (12.4 MB) (android-boot)
│   ├── 📄 kernel (8.1 MB)
│   ├── 📄 ramdisk (3.2 MB)
│   └── 📄 second (128 KB)
~~~

### MBR / GPT

Imagem de disco com tabela de partições. Lista cada partição; cada uma é
reaberta pelo handler do filesystem interno.

~~~
├── 🗜️ **disco.img** (4.0 GB) (disk)
│   ├── 📄 boot (64 MB)
│   ├── 📄 rootfs (3.4 GB)
│   └── 📄 persist (32 MB)
~~~

---

## 🟡 Python opcional (pip)

### `.zst` / `.tzst`

Requer `zstandard` (pip) ou o binário `zstd`. Alternativa pura-Python.

### `.iso`

Requer `pycdlib` (pip) ou `isoinfo` (genisoimage). **Lista apenas** —
transcrever exigiria extrair para tempdir.

### `.7z`

Requer `py7zr` (pip) ou `7z` (p7zip). Ambos leem e transcrevem.

---

## 🔴 Ferramentas externas (binários de sistema)

### `simg2img` — Android sparse image

Magic `\x3a\xff\x26\xed`. Não é um archive, é uma **representação eficiente em
blocos**. Para ler o filesystem dentro, o script converte via `simg2img` num
tempfile e reabre o resultado.

~~~
boot.bin (sparse)
  ↓ simg2img
boot-raw.img (ext4)
  ↓ debugfs
/extlinux/extlinux.conf
~~~

Isso é **crítico para o OpenDongle**: `boot.bin` e `rootfs.bin` são sparse.

### `debugfs` (e2fsprogs) — ext2/3/4

Lê `.img` com ext. Recursa em subdiretórios via `ls -l -p`, lê arquivos via `cat`.
Nada é montado, nada precisa de sudo.

### `mdir` (mtools) — FAT12/16/32

Lista `.img` com FAT. **Não transcreve** — extrair exigiria montar.

### `unsquashfs` (squashfs-tools) — squashfs

Magic `hsqs` ou `sqsh`. **Lista apenas** — extrair exige tempdir + caminho.

### `isoinfo` (genisoimage) ou `pycdlib` — ISO 9660

Magic `CD001` em offset 32769. **Lista apenas**, pelos mesmos motivos.

### `7z` (p7zip) — `.7z`, `.rar`

Canivete suíço. Lê 7z, rar, iso, zip, tar, gzip, e mais. Usado como fallback
para formatos que não têm handler nativo.

### `unrar` (unrar-free/unrar) — `.rar`

Backend para `.rar`. Alguns distros não empacotam por licença; nesse caso o
`7z` cobre.

### `file` — fallback genérico

Usado quando o magic não bate e a extensão é `.img`/`.bin`. Pergunta ao `file`
o que é e roteia.

---

## 📊 Matriz de decisão

Se o script encontrar um arquivo, ele decide assim:

~~~
1. Magic bytes casam com MAGIC?
   ├── Sim → handler direto
   └── Não → continua

2. Extensão em EXT_HINTS?
   ├── Sim → handler por extensão
   └── Não → continua

3. Extensão é .img/.bin?
   ├── Sim → pergunta ao 'file'
   └── Não → trata como arquivo normal
~~~

O resultado: um `.xyz` desconhecido com magic de zip é tratado como zip. Um
`.tar.gz` renomeado para `.tgz.backup` ainda é reconhecido pelo magic. E um
`.img` genérico passa pelo `file -b` que identifica o filesystem real.

---

## 🚧 Formatos que **não** são suportados (e por quê)

| Formato | Motivo |
|---|---|
| `.rar` sem `unrar` nem `7z` | Sem decoder disponível |
| `.img` com UDF (DVD) | `file` identifica, mas nenhum handler abre |
| `.iso` com Rock Ridge/Joliet complexo | `isoinfo` lista, mas nomes podem sair truncados |
| `.7z` com compressão PPMd | `py7zr` pode falhar; `7z` cobre |
| `.zip` com criptografia AES | `zipfile` da stdlib não abre |
| `.tar.zst` sem `zstandard` | Não há decoder zstd no stdlib |

Em todos esses casos, o script reporta e continua — nunca trava.
