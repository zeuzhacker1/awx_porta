# collect-pre-update-data collect PI package directories Bash script


#source ./_shared.sh


: ${PI_APPDIR:=/porta_var/.pi/app}
: ${PI_APPBIN:=${PI_APPDIR}/bin/pi.sh}



main() {
    local current_mr=${1:-''}
    current_mr=${current_mr:-$(get_cur_mr)}
    local pi_appbin=${2:-${PI_APPBIN}}

    ${pi_appbin} cf show sinks extended -r${current_mr} \
    | cut -f2 | sort -u
}


if [[ -z ${_LOADED_SHARED+x} ]]; then
    echo 'MISSING SHARED LIB' >&2
    exit 255
else
    main "${@}"
fi

