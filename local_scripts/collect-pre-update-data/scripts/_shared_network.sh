# collect-pre-update-data network check/backup shared Bash functions


#source ./_shared.sh


# Special variable used to prevent unsafe execution of other scripts
_LOADED_SHARED_NETWORK=true


: ${NETWORK_SCRIPTS_GLOBAL:=/etc/sysconfig/network}
: ${NETWORK_SCRIPTS_DIR:=/etc/sysconfig/network-scripts}
: ${NETWORK_KEYFILES_DIR:=/etc/NetworkManager/system-connections}


# Runtime variables, don't touch
MODE=



# Before MR114 we used OL8 and below with legacy init network scripts.
# These remained in use despite NetworkManager being introduced in MR108.
# After MR114, before migrating to OL9+ where legacy scripts
# are deprecated, we started using NetworkManager keyfiles instead.
switch_mode() {
    local mode=${1}

    case ${mode} in
        'network_scripts'|'network_keyfiles')
            MODE=${mode} ;;
        '')
            is_keyfile_enforced \
            && MODE='network_keyfiles' \
            || MODE='network_scripts' ;;
        *)
            set_code 1 'Unknown mode requested'
            return ${EXIT_CODE} ;;
    esac
}

is_keyfile_enforced() {
    is_keyfile_enforced_pc \
    && is_keyfile_enforced_nm
}

is_keyfile_enforced_pc() {
    grep -Fxq 'use_nm_keyfile=1' \
        ${AGENT_CONF_FILE:-${PORTACONFIGURATOR_HOME:?'MISSING SHARED LIB'}/etc/porta-agent.conf}
}

is_keyfile_enforced_nm() {
    find ${NETWORKMANAGER_CONF_D:-/etc/NetworkManager/conf.d} -type f \
    | sort \
    | { xargs -n1 grep -Eh '^plugins=' || true; } \
    | tail -1 \
    | grep -Eq '^plugins=keyfile'
}

