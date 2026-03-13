# collect-pre-update-data check network scripts/keyfiles Bash script


#source ./_shared.sh
#source ./_shared_network.sh


NETWORK_CHECK_MSG_TEMPLATE_INTERTNAL_ERROR=$(cat <<- 'ACHTUNG'
	Internal error occurred: %s

	Internal errors mean issue in suite's underlying logic.
	Don't waste your time and submit the case for maintainer's attention.
ACHTUNG
)
NETWORK_CHECK_MSG_NO_DEFAULT_GATEWAY_IN_RUNTIME=$(cat <<- 'ACHTUNG'
	Default gateway is missing in runtime!

	This means that the server has no default (fallback) route set right now
	and network packages routing might be incorrect since packages that
	don't suit any non-default route might be discarded resulting in issues.

	Please recheck the network configuration on the server and fix this.
	YOU ARE NOT ALLOWED TO EXECUTE UPDATE UNLESS THE ISSUE IS FIXED!
ACHTUNG
)
NETWORK_CHECK_MSG_TEMPLATE_MISSING_GATEWAYS_IN_CONFIGS=$(cat <<- 'ACHTUNG'
	The following gateways are missing in resolved active configs: %s

	This means that once you reboot the server you'll likely experience
	connectivity issues in best case. In worst case the server will be
	unreachable at all and you'll have to use KVM access or escalate case.

	"resolved active configs" means configuration files that are currently
	associated with network interfaces that handling the affected gateways,
	or configuration files that cover global scope (only before MR114).

	It's possible that you'll find gateways in files that don't cover
	those interfaces right now in runtime. Make sure that configuration
	on-disk and in runtime is indeed the same for sure before proceeding.

	E.g., you might find foo-iface.nmconnection file when in runtime
	connection is named bar-iface, which means configuration on-disk
	and in runtime is likely different and this might cause issues.

	Please recheck the network configuration on the server and fix issue.
	YOU ARE NOT ALLOWED TO EXECUTE UPDATE UNLESS THE ISSUE IS FIXED!
ACHTUNG
)


# Runtime variables, don't touch
RUNTIME_GATEWAYS=()
declare -gA \
    FACT_FOUND_GATEWAY_GLOBAL=() \
    FACT_FOUND_GATEWAY_IFACE=()



get_gateways() {
    netstat -nr | grep -E '^(0\.){3}0' | cut -d' ' -f10
}

load_gateways() {
    RUNTIME_GATEWAYS=( $(get_gateways || true) )

    [[ ${#RUNTIME_GATEWAYS[@]} -ne 0 ]] \
    || {
        set_code 1 "${NETWORK_CHECK_MSG_NO_DEFAULT_GATEWAY_IN_RUNTIME}"
        return ${EXIT_CODE}
    }
    local gateway=

    for gateway in ${RUNTIME_GATEWAYS[@]}; do
        FACT_FOUND_GATEWAY_GLOBAL[${gateway}]=false
        FACT_FOUND_GATEWAY_IFACE[${gateway}]=false
    done
}

switch_gateway_fact() {
    local gateway=${1:?'gateway which fact to switch is required'}
    local storage=${2:?'name of dictionary is required'}
    local fact=${3:?'either true or false is required'}

    local -n storage=${storage}

    ${storage[${gateway}]} \
    && return 0 \
    || storage[${gateway}]=${fact}
}

assert_gateway_loaded() {
    local gateway=${1:?'gateway to assert is required'}
    [[
        -n ${FACT_FOUND_GATEWAY_GLOBAL[${gateway}]:+x} \
        && -n ${FACT_FOUND_GATEWAY_IFACE[${gateway}]:+x}
    ]] \
    || {
        set_code 1 "$(
            printf \
                "${NETWORK_CHECK_MSG_TEMPLATE_INTERTNAL_ERROR}\n" \
                "gateway ${gateway} fact state corrupted"
        )"
        return ${EXIT_CODE}
    }
}


check_gateway_present_on_disk_main() {
    local gateway=${1:?'gateway to check in on-disk config is required'}
    local config=${2:?'config to check is required'}
    assert_gateway_loaded ${gateway}

    [[ ${MODE} == 'network_scripts' ]] \
    && local regex='GATEWAY=' \
    || local regex='route[0-9]+=(0\.){3}0|gateway=|address[0-9]+=[^,]+,'

    sudo grep -E "${gateway//./\\.}$" "${config}" 2>/dev/null \
    | grep -Eqi "${regex}"
}

check_gateway_present_on_disk_routes() {
    local gateway=${1:?'gateway to check in on-disk config is required'}
    local config=${2:?'config to check is required'}
    assert_gateway_loaded ${gateway}

    [[ ${MODE} == 'network_scripts' ]] \
    && local regex='(0\.){3}0/0 via ' \
    || return 1

    sudo grep -E "via ${gateway//./\\.} " "${config}" 2>/dev/null \
    | grep -Eqi "${regex}"
}


get_ifaces() {
    ip addr | grep -E 'inet\s{1}' | awk '{print $NF}' \
    | grep -Ev 'lo|dia|sip|web|fwd|rc|docker|br-' \
    | sort | uniq \
    || {
        set_code 1 "$(
            printf \
                "${NETWORK_CHECK_MSG_TEMPLATE_INTERTNAL_ERROR}\n" \
                'Cannot retireve ifaces'
        )"
        return ${EXIT_CODE}
    }
}

get_iface_connection() {
    local iface=${1:?'interface name is required'}
    nmcli device show ${iface} \
    | sed -En '/GENERAL\.CONNECTION/s/^[^:]+:\s*(.+)\s*$/\1/gp'
}

get_iface_config_main() {
    local iface=${1:?'interface name is required'}
    [[ ${MODE} == 'network_scripts' ]] \
    && echo ${NETWORK_SCRIPTS_DIR}/ifcfg-${iface} \
    || echo ${NETWORK_KEYFILES_DIR}/$(get_iface_connection ${iface}).nmconnection
}

get_iface_config_routes() {
    local iface=${1:?'interface name is required'}
    [[ ${MODE} != 'network_scripts' ]] \
    || echo ${NETWORK_SCRIPTS_DIR}/route-${iface}
}


check_gateways_present_global() {
    # NM don't have such meaning in keyfiles as global gateway
    [[ ${MODE} == 'network_scripts' ]] \
    || return 0

    local gateway=

    for gateway in ${RUNTIME_GATEWAYS[@]}; do
        check_gateway_present_on_disk_main ${gateway} ${NETWORK_SCRIPTS_GLOBAL} \
        && switch_gateway_fact ${gateway} FACT_FOUND_GATEWAY_GLOBAL true \
        || switch_gateway_fact ${gateway} FACT_FOUND_GATEWAY_GLOBAL false
    done
}

check_gateways_present_ifaces() {
    local ifaces=() iface= config_main= config_routes= gateway=

    ifaces=( $(get_ifaces) ) \
    || {
        set_code ${?}
        return ${EXIT_CODE}
    }

    for iface in ${ifaces[@]}; do
        config_main=$(get_iface_config_main ${iface})
        config_routes=$(get_iface_config_routes ${iface})

        for gateway in ${!FACT_FOUND_GATEWAY_GLOBAL[@]}; do
            ! ${FACT_FOUND_GATEWAY_GLOBAL[${gateway}]} \
            || continue

            {
                check_gateway_present_on_disk_main ${gateway} "${config_main}" \
                || {
                    [[ -n ${config_routes:+x} ]] \
                    && check_gateway_present_on_disk_routes ${gateway} "${config_routes}"
                }
            } \
            && switch_gateway_fact ${gateway} FACT_FOUND_GATEWAY_IFACE true \
            || switch_gateway_fact ${gateway} FACT_FOUND_GATEWAY_IFACE false
        done
    done
}


summarize_gateways_checks() {
    local gateway= affected_gateways=()

    for gateway in ${!FACT_FOUND_GATEWAY_GLOBAL[@]}; do
        ! ${FACT_FOUND_GATEWAY_GLOBAL[${gateway}]} \
        || continue

        ${FACT_FOUND_GATEWAY_IFACE[${gateway}]} \
        || affected_gateways+=( ${gateway} )
    done

    [[ ${#affected_gateways[@]} -ne 0 ]] \
    || {
        echo 'All gateways are present in on-disk configuration files'
        return 0
    }
    set_code 1 "$(
        printf \
            "${NETWORK_CHECK_MSG_TEMPLATE_MISSING_GATEWAYS_IN_CONFIGS}\n" \
            "${affected_gateways[@]}"
    )"
}



main() {
    switch_mode ${1}

    load_gateways

    check_gateways_present_global
    check_gateways_present_ifaces

    summarize_gateways_checks

    exit ${EXIT_CODE}
}


if [[ -z ${_LOADED_SHARED+x} ]]; then
    echo 'MISSING SHARED LIB' >&2
    exit 255
elif [[ -z ${_LOADED_SHARED_NETWORK+x} ]]; then
    echo 'MISSING SHARED NETWORK LIB' >&2
    exit 255
else
    main "${@}"
fi

