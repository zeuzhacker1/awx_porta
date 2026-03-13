# collect-pre-update-data collect check_patches_f Bash script


#source ./_shared.sh


: ${PCUP_UPDT_BIN:=${PORTACONFIGURATOR_HOME}/pcup/update/bin}
: ${CHECK_PATCHES_F_EXEC:=${PCUP_UPDT_BIN}/check_patches_f}



main() {
    local current_mr=${1:-''}
    current_mr=${current_mr:-$(get_cur_mr | tr \. -)}
    local check_patches_f_exec=${2:-${CHECK_PATCHES_F_EXEC}}

    sudo ${check_patches_f_exec} \
        -o current_partition=mr${current_mr} \
        -o backup=1 \
    || true
}


if [[ -z ${_LOADED_SHARED+x} ]]; then
    echo 'MISSING SHARED LIB' >&2
    exit 255
elif [[ -z ${_LOADED_SHARED_WATCHDOG+x} ]]; then
    echo 'MISSING SHARED WATCHDOG LIB' >&2
    exit 255
else
    main "${@}"
fi

