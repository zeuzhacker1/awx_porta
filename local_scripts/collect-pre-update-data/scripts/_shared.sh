# collect-pre-update-data shared auxiliary Bash functions


# Special variable used to prevent unsafe execution of other scripts
_LOADED_SHARED=true


declare -gA COLORS
COLORS[GREEN]='\e[92m'
COLORS[RED]='\e[91m'
COLORS[RESET]='\e[0m'

USE_COLORS=false


: ${PORTACONFIGURATOR_HOME:=/home/porta-configurator}
: ${CPUD_TMP_DIR:=/porta_var/tmp/collect_pre_update_data}


# Runtime variables, don't touch
EXIT_CODE=0
MY_TMP_DIR=

# Prevent overwrites in case of buggy invocation
if [[ -z "$(trap)" ]]; then
    trap 'cleanup_tmp' SIGINT SIGTERM EXIT
fi



extend_trap() {
    local func=${1:?'callable for trap is required'}
    shift

    local sigs=( ${@:?'signals which trap to extend are required'} )
    local sig=

    for sig in ${sigs[@]}; do
        trap \
            "$(trap -p ${sig} | sed -E "s/^[^']+'(.+)' [^ ]+/\1/"); ${func}" \
            ${sig}
    done
}


msg_info() {
    local msg=${1:?'message to log is required'}
    ${USE_COLORS} \
    && echo -e "${COLORS['GREEN']}${msg}${COLORS['RESET']}" >&2 \
    || echo "!!! IMPORTANT INFO: ${msg}" >&2
}

msg_error() {
    local msg=${1:?'message to log is required'}
    ${USE_COLORS} \
    && echo -e "${COLORS['RED']}${msg}${COLORS['RESET']}" >&2 \
    || echo "!!! IMPORTANT ERROR: ${msg}" >&2
}

set_code() {
    local code=${1:?'error code to set is required'}
    local msg=${2}

    if [[ -n ${msg:+x} ]]; then
        [[ ${code} -eq 0 ]] \
        && msg_info "${msg}" \
        || msg_error "${msg}"
    fi
    EXIT_CODE=${code}
}


make_separator_line() {
    local separator_len=${1:?'multiplication factor is required'}
    local separator_char=${2:--}

    printf -- "${separator_char}%.0s" $(seq 1 ${separator_len})
    echo
}

# Expects STDIN
format_output() {
    local prefix=${1:?'output identity for prefix is required'}

    local separator=
    separator=$(make_separator_line "${#prefix}")

    local safe_prefix=
    safe_prefix=${prefix//\\/\\\\}
    safe_prefix=${safe_prefix//&/\\&}
    safe_prefix=${safe_prefix//\//\\\/}

    echo "${separator} \\"
    sed "s/^/${safe_prefix} | /"
    echo "${separator} /"
}


get_cur_mr() {
    rpm -q --queryformat '%{VERSION}' porta-common
}


lmktemp() {
    if [[ ! -d ${CPUD_TMP_DIR} ]]; then
        mkdir -p ${CPUD_TMP_DIR}
    fi
    if [[ -z ${MY_TMP_DIR:+x} ]]; then
        MY_TMP_DIR=$(TMPDIR=${CPUD_TMP_DIR} mktemp -d)
    fi
    env TMPDIR=${MY_TMP_DIR} mktemp "${@}"
}

cleanup_tmp() {
    [[ -n ${MY_TMP_DIR:+x} ]] || return
    [[ ! -d "${MY_TMP_DIR}" ]] || rm -rf "${MY_TMP_DIR}"
}

