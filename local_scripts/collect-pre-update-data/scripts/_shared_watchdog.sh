# collect-pre-update-data parent process shared watchdog


#source ./_shared.sh


# Special variable used to prevent unsafe execution of other scripts
_LOADED_SHARED_WATCHDOG=true


# Runtime variables, don't touch
ORIGINAL_PARENT=${PPID}
ORIGINAL_SELF=${$}



cleanup_procs() {
    sudo kill -SIGKILL 0
}

watchdog() {
    local watch_pid=${1:?'PID to watch is required'}
    sleep 1s

    while kill -0 ${ORIGINAL_SELF} &>/dev/null; do
        kill -0 ${watch_pid} &>/dev/null \
        && sleep 1s \
        || break
    done

    cleanup_procs
}


if [[ -z ${_LOADED_SHARED+x} ]]; then
    echo 'MISSING SHARED LIB' >&2
    exit 255
else
    watchdog ${ORIGINAL_PARENT} &
fi

