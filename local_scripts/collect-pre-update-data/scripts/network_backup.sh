# collect-pre-update-data backup network scripts/keyfiles Bash script


#source ./_shared.sh
#source ./_shared_network.sh


: ${IPROUTE2_ROUTING_TABLES:=/etc/iproute2/rt_tables}


# Runtime variables, don't touch
FACT_NM_ACTIVE=false



switch_nm_collection() {
    systemctl is-active NetworkManager &>/dev/null \
    && FACT_NM_ACTIVE=true \
    || FACT_NM_ACTIVE=false
}



check_custom_ip_rules() {
    ip rule | grep -Eqv 'local|main|default'
}

get_iproute_tables() {
    ip rule | grep -Ev 'local|main|default' \
    | grep -Eo 'lookup .+' | cut -d' ' -f2 | sort -u || true
}

dump_iproute_tables_runtime() {
    local table=

    for table in $(get_iproute_tables); do
        ip route show table ${table} \
        |& format_output "iproute2 table ${table}" || true
    done
}

dump_iproute() {
    ip addr  |& format_output 'iproute2 addrs'
    ip route |& format_output 'iproute2 routes'

    ! check_custom_ip_rules || {
        ip rule |& format_output 'iproute2 rules'
        dump_iproute_tables_runtime
    }
}


dump_networkmanager() {
    {
        nmcli --fields DEVICE device \
        | sed '1d; s/\s*$//' \
        | while IFS=$'\n' read -r nm_dev; do
            nmcli device show "${nm_dev}" \
            |& format_output "${nm_dev}"
        done
    } \
    |& format_output 'NetworkManager devices'

    {
        nmcli --fields NAME connection show \
        | sed '1d; s/\s*$//' \
        | while IFS=$'\n' read -r nm_con; do
            nmcli connection show "${nm_con}" \
            |& format_output "${nm_con}"
        done
    } \
    |& format_output 'NetworkManager connections'
}


dump_iptables() {
    sudo iptables-save \
    |& format_output 'iptables' || true
}


dump_runtime() {
    {
        dump_iproute
        ! ${FACT_NM_ACTIVE} || dump_networkmanager
        dump_iptables
    } \
    |& format_output 'Runtime configs'
}



dump_ifcfgs() {
    sudo grep -H ^ ${NETWORK_SCRIPTS_GLOBAL}
    sudo bash -c "grep -H ^ ${NETWORK_SCRIPTS_DIR}/ifcfg-*"
    sudo bash -c "grep -H ^ ${NETWORK_SCRIPTS_DIR}/route-*"
    sudo bash -c "grep -H ^ ${NETWORK_SCRIPTS_DIR}/rule-*"
}

dump_keyfiles() {
    sudo bash -c "grep -H ^ ${NETWORK_KEYFILES_DIR}/*.nmconnection"
}

dump_iproute_tables_on_disk() {
    sudo grep -H ^ ${IPROUTE2_ROUTING_TABLES}
}


dump_on_disk() {
    {
        [[ ${MODE} == 'network_scripts' ]] \
        && { dump_ifcfgs || true; } \
        || { dump_keyfiles || true; }

        dump_iproute_tables_runtime || true
    } \
    |& format_output 'On-disk configs'
}



main() {
    switch_mode ${1}
    switch_nm_collection

    dump_runtime
    dump_on_disk
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

