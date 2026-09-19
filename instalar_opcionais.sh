#!/usr/bin/env bash
# ============================================================
# instalar_opcionais.sh
# Instala as ferramentas opcionais de sistema para o
# Tree Content Generator. Idempotente: pode rodar várias vezes.
#
# Uso:
#   ./instalar_opcionais.sh                 # instala tudo (pede sudo)
#   ./instalar_opcionais.sh --pip           # instala só os pacotes Python
#   ./instalar_opcionais.sh --sistema       # instala só os binários de sistema
#   ./instalar_opcionais.sh --listar        # só mostra o que já tem / falta
#   ./instalar_opcionais.sh --sem-pip       # sistema apenas, sem tocar em pip
#   ./instalar_opcionais.sh --sem-rar       # pula unrar (licença restritiva)
# ============================================================

set -u

# ---------- cores ----------
if [ -t 1 ]; then
    C_OK="\033[92m"; C_ER="\033[91m"; C_AV="\033[93m"
    C_IN="\033[94m"; C_BO="\033[1m"; C_END="\033[0m"
else
    C_OK=""; C_ER=""; C_AV=""; C_IN=""; C_BO=""; C_END=""
fi

ok()   { printf "${C_OK}  ✓ %s${C_END}\n" "$*"; }
falta(){ printf "${C_ER}  ✗ %s${C_END}\n" "$*"; }
info() { printf "${C_IN}ℹ️  %s${C_END}\n" "$*"; }
aviso(){ printf "${C_AV}⚠️  %s${C_END}\n" "$*"; }
titulo(){ printf "\n${C_BO}== %s ==${C_END}\n" "$*"; }

# ---------- argumentos ----------
FAZER_PIP=1
FAZER_SISTEMA=1
SO_LISTAR=0
PULAR_RAR=0

for arg in "$@"; do
    case "$arg" in
        --pip)       FAZER_SISTEMA=0 ;;
        --sistema)   FAZER_PIP=0 ;;
        --sem-pip)   FAZER_PIP=0 ;;
        --sem-rar)   PULAR_RAR=1 ;;
        --listar)    SO_LISTAR=1 ;;
        -h|--help)
            sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
            exit 0 ;;
        *)
            echo "Argumento desconhecido: $arg" >&2
            exit 1 ;;
    esac
done

# ---------- detecção de distro ----------
detectar_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        case "${ID:-}" in
            debian|ubuntu|linuxmint|pop|raspbian|kali)
                echo "apt" ;;
            fedora|rhel|centos|rocky|almalinux)
                echo "dnf" ;;
            arch|manjaro|endeavouros|garuda)
                echo "pacman" ;;
            *)
                case "${ID_LIKE:-}" in
                    *debian*|*ubuntu*) echo "apt" ;;
                    *fedora*|*rhel*)   echo "dnf" ;;
                    *arch*)            echo "pacman" ;;
                    *)                 echo "desconhecido" ;;
                esac ;;
        esac
    elif command -v apt    >/dev/null 2>&1; then echo "apt"
    elif command -v dnf    >/dev/null 2>&1; then echo "dnf"
    elif command -v pacman >/dev/null 2>&1; then echo "pacman"
    else echo "desconhecido"
    fi
}

# ---------- binários necessários ----------
BINARIOS=(
    "7z|7z|p7zip-full|p7zip p7zip-plugins|p7zip"
    "simg2img|simg2img|simg2img|android-tools|android-tools"
    "debugfs|debugfs|e2fsprogs|e2fsprogs|e2fsprogs"
    "mdir|mdir|mtools|mtools|mtools"
    "isoinfo|isoinfo|genisoimage|genisoimage|cdrtools"
    "unsquashfs|unsquashfs|squashfs-tools|squashfs-tools|squashfs-tools"
    "file|file|file|file|file"
)

RAR_BINARIO="unrar"
RAR_PACOTES="unrar-free|unrar|unrar"

# ---------- checagem e listagem ----------
listar_estado() {
    titulo "Binários de sistema"
    for linha in "${BINARIOS[@]}"; do
        IFS='|' read -r rotulo bin _ <<< "$linha"
        if command -v "$bin" >/dev/null 2>&1; then
            ok "$rotulo  ($(command -v "$bin"))"
        else
            falta "$rotulo  (falta o binário '$bin')"
        fi
    done
    if [ "$PULAR_RAR" -eq 0 ]; then
        if command -v "$RAR_BINARIO" >/dev/null 2>&1; then
            ok "rar  ($(command -v "$RAR_BINARIO"))"
        else
            falta "rar  (opcional, alguns distros não empacotam)"
        fi
    fi

    titulo "Pacotes Python (opcionais)"
    for pacote in pycdlib zstandard py7zr chardet; do
        if python3 -c "import $pacote" 2>/dev/null; then
            ok "$pacote"
        else
            falta "$pacote"
        fi
    done
}

# ---------- instalação via pip ----------
instalar_pip() {
    titulo "Pacotes Python via pip"
    if ! command -v python3 >/dev/null 2>&1; then
        aviso "python3 não encontrado — pulando pip"
        return
    fi
    if ! python3 -m pip --version >/dev/null 2>&1; then
        aviso "pip não está disponível para o python3 — instale 'python3-pip'"
        return
    fi

    if [ -f "requirements.txt" ]; then
        info "Usando requirements.txt do diretório atual"
        if python3 -m pip install --user -r requirements.txt 2>/dev/null; then
            ok "requirements.txt instalado (modo --user)"
        elif python3 -m pip install --user --break-system-packages -r requirements.txt 2>/dev/null; then
            ok "requirements.txt instalado (--user --break-system-packages)"
        else
            aviso "pip falhou. Tente: python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt"
        fi
    else
        info "requirements.txt não encontrado; instalando pacotes individuais"
        python3 -m pip install --user \
            pycdlib zstandard py7zr chardet 2>/dev/null \
            || python3 -m pip install --user --break-system-packages \
               pycdlib zstandard py7zr chardet 2>/dev/null \
            || aviso "pip falhou (tente num venv)"
    fi
}

# ---------- instalação dos binários ----------
instalar_sistema_apt() {
    local pacotes=()
    for linha in "${BINARIOS[@]}"; do
        IFS='|' read -r _ bin _ apt_pkg _ <<< "$linha"
        if ! command -v "$bin" >/dev/null 2>&1; then
            for p in $apt_pkg; do pacotes+=("$p"); done
        fi
    done
    if [ "$PULAR_RAR" -eq 0 ] && ! command -v "$RAR_BINARIO" >/dev/null 2>&1; then
        IFS='|' read -r p_apt _ _ <<< "$RAR_PACOTES"
        pacotes+=("$p_apt")
    fi

    if [ "${#pacotes[@]}" -eq 0 ]; then
        ok "Todos os binários de sistema já estão instalados"
        return
    fi

    info "Pacotes a instalar via apt: ${pacotes[*]}"
    if ! sudo apt update -qq; then
        aviso "apt update falhou — seguindo mesmo assim"
    fi
    if sudo DEBIAN_FRONTEND=noninteractive apt install -y --no-install-recommends "${pacotes[@]}"; then
        ok "Instalado via apt"
    else
        aviso "Alguma coisa falhou em apt — veja a saída acima"
    fi
}

instalar_sistema_dnf() {
    local pacotes=()
    for linha in "${BINARIOS[@]}"; do
        IFS='|' read -r _ bin _ _ dnf_pkg <<< "$linha"
        if ! command -v "$bin" >/dev/null 2>&1; then
            for p in $dnf_pkg; do pacotes+=("$p"); done
        fi
    done
    if [ "$PULAR_RAR" -eq 0 ] && ! command -v "$RAR_BINARIO" >/dev/null 2>&1; then
        IFS='|' read -r _ _ dnf_pkg <<< "$RAR_PACOTES"
        pacotes+=("$dnf_pkg")
    fi
    if [ "${#pacotes[@]}" -eq 0 ]; then
        ok "Todos os binários de sistema já estão instalados"
        return
    fi
    info "Pacotes a instalar via dnf: ${pacotes[*]}"
    if sudo dnf install -y "${pacotes[@]}"; then
        ok "Instalado via dnf"
    else
        aviso "dnf falhou — veja a saída acima"
    fi
}

instalar_sistema_pacman() {
    local pacotes=()
    for linha in "${BINARIOS[@]}"; do
        IFS='|' read -r _ bin _ _ _ pac_pkg <<< "$linha"
        if ! command -v "$bin" >/dev/null 2>&1; then
            for p in $pac_pkg; do pacotes+=("$p"); done
        fi
    done
    if [ "$PULAR_RAR" -eq 0 ] && ! command -v "$RAR_BINARIO" >/dev/null 2>&1; then
        IFS='|' read -r _ _ _ pac_pkg <<< "$RAR_PACOTES"
        pacotes+=("$pac_pkg")
    fi
    if [ "${#pacotes[@]}" -eq 0 ]; then
        ok "Todos os binários de sistema já estão instalados"
        return
    fi
    info "Pacotes a instalar via pacman: ${pacotes[*]}"
    if sudo pacman -S --needed --noconfirm "${pacotes[@]}"; then
        ok "Instalado via pacman"
    else
        aviso "pacman falhou — veja a saída acima"
    fi
}

instalar_sistema() {
    local distro
    distro=$(detectar_distro)
    titulo "Binários de sistema (distro: $distro)"
    case "$distro" in
        apt)     instalar_sistema_apt ;;
        dnf)     instalar_sistema_dnf ;;
        pacman)  instalar_sistema_pacman ;;
        *)
            aviso "Distro não reconhecida. Instale manualmente:"
            echo "     • 7z (p7zip-full / p7zip)"
            echo "     • simg2img (Android tools)"
            echo "     • e2fsprogs (debugfs)"
            echo "     • mtools (mdir)"
            echo "     • genisoimage / cdrtools (isoinfo)"
            echo "     • squashfs-tools (unsquashfs)"
            echo "     • file"
            ;;
    esac
}

# ---------- main ----------
titulo "Tree Content Generator — instalador de opcionais"
info "Modo: $( [ "$SO_LISTAR" -eq 1 ] && echo 'listar' || echo 'instalar' )"
[ "$FAZER_PIP" -eq 1 ] && [ "$SO_LISTAR" -eq 0 ] && info "pip: ativado"
[ "$FAZER_SISTEMA" -eq 1 ] && [ "$SO_LISTAR" -eq 0 ] && info "sistema: ativado"

listar_estado

if [ "$SO_LISTAR" -eq 1 ]; then
    titulo "Fim (modo listar)"
    exit 0
fi

[ "$FAZER_PIP" -eq 1 ]     && instalar_pip
[ "$FAZER_SISTEMA" -eq 1 ] && instalar_sistema

titulo "Estado final"
listar_estado

titulo "Pronto"
info "Rode o gerador:  python3 geradordepastasearquivos.py"
info "Ele vai mostrar no diagnóstico inicial o que foi detectado."
