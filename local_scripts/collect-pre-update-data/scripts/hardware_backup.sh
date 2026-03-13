# collect-pre-update-data backup hardware configuration Bash script


#source ./_shared.sh


: ${PORTACONFIGURATOR_HOME:=/home/porta-configurator}
: ${CFGCTL_EXEC:=${PORTACONFIGURATOR_HOME}/bin/cfgctl.pl}


: ${STORCLI_EXEC:=/opt/MegaRAID/storcli/storcli64}

: ${SSA_CLI_EXEC:=/usr/sbin/ssacli}
: ${HP_SSA_CLI_EXEC:=/usr/sbin/hpssacli}
: ${HP_ACU_CLI_EXEC:=/usr/sbin/hpacucli}
: ${HPE_DISK_CLI_EXEC:=/opt/smartstorageadmin/ssacli/bin/ssacli}

CCISS_CLI_EXECS=(
    ${SSA_CLI_EXEC}
    ${HP_SSA_CLI_EXEC}
    ${HP_ACU_CLI_EXEC}
    ${HPE_DISK_CLI_EXEC}
)



get_server_info() {
    ${CFGCTL_EXEC} -c server_info -p acquire_netinfo=0 \
    | grep -Ei 'CPU|RAM|RAID controller|HOST|MANUF|OS|Hypervisor' \
    |& format_output 'Server info'
}


get_raid_type() {
    ls -1 /sys/bus/pci/drivers/ \
    | grep -Eo 'megaraid_sas|3w-xxxx|cciss|hpsa|mptsas|mpt2sas|3w-9xxx|aacraid|arcmsr|smartpqi|hpilo|hpwdt' \
    | head -1 \
    || {
        set_code 1 "No known RAID detected"
        return ${EXIT_CODE}
    }
}

mangle_raid_type() {
    local raid_type=${1:?'raid type is required'}
    tr -s '-' '_' <<< ${raid_type}
}

switch_raid_collection() {
    local raid_type=${1:?'raid type is required'}
    raid_type=$(mangle_raid_type ${raid_type})

    local collect_raid_method=collect_raid__${raid_type}

    declare -F ${collect_raid_method} >/dev/null \
    || {
        set_code 1 "Unsupported RAID detected: ${raid_type}"
        return ${EXIT_CODE}
    }

    ${collect_raid_method}
}

collect_raid__megaraid_sas() {
    if [[ -f ${STORCLI_EXEC} ]]; then
        collect_raid__megaraid_sas_storcli
    else
        collect_raid__megaraid_sas_megacli
    fi
}

collect_raid__megaraid_sas_megacli() {
    sudo megacli -ShowSummary -a0 \
    |& format_output 'RAID megacli ShowSummary'

    sudo megacli -AdpBbuCmd -aAll \
    |& format_output 'RAID megacli AdpBbuCmd'
}

collect_raid__megaraid_sas_storcli() {
    sudo ${STORCLI_EXEC} /c0/vall show all nolog \
    |& format_output 'RAID storcli vall show'

    local f_bbu_show= bbu_show_retcode=
    f_bbu_show=$(lmktemp)

    sudo ${STORCLI_EXEC} /c0/bbu show all nolog \
    |& format_output 'RAID storcli bbu show' &> ${f_bbu_show} \
    && cat ${f_bbu_show} \
    || {
        bbu_show_retcode=${?}

        grep -Eq ' +use /cx/cv +' ${f_bbu_show} \
        || { cat ${f_bbu_show}; return ${bbu_show_retcode}; }

        sudo ${STORCLI_EXEC} /c0/cv show all nolog \
        |& format_output 'RAID storcli cv show' \
        || return ${?}
    }
}

collect_raid__cciss() {
    local possible_cli_exec= available_cli_exec=

    local f_show_status=
    f_show_status=$(lmktemp)

    for possible_cli_exec in "${CCISS_CLI_EXECS[@]}"; do
        [[ ! -f ${possible_cli_exec} ]] \
        || {
            sudo ${possible_cli_exec} ctrl all show status \
            |& format_output "RAID $(basename ${possible_cli_exec}) show status" &> ${f_show_status} \
            && { available_cli_exec=${possible_cli_exec}; break; }
        }
    done

    [[ -n ${available_cli_exec:+x} ]] \
    || {
        set_code 1 "No suitable RAID utility found within the following list: ${CCISS_CLI_EXECS[*]}"
        return ${EXIT_CODE}
    }

    cat ${f_show_status}

    sudo ${available_cli_exec} ctrl all show config detail \
    |& format_output "RAID $(basename ${available_cli_exec}) show config"
}

collect_raid__hpsa() {
    collect_raid__cciss
}

#TODO: once suitable hardware found:
# 1. Replace with actual tested ilorest commands.
collect_raid__hpilo() {
    collect_raid__hpsa
}

#TODO: once suitable hardware found:
# 1. Replace with actual tested ilorest commands.
collect_raid__hpwdt() {
    collect_raid__hpsa
}

collect_raid__aacraid() {
    sudo arcconf GETCONFIG 1 \
    |& format_output 'RAID arcconf config'
}



main() {
    get_server_info

    local raid_type=
    raid_type=$(get_raid_type || true)

    if [[ -n ${raid_type:+x} ]]; then
        switch_raid_collection ${raid_type}
    fi
}


if [[ -z ${_LOADED_SHARED+x} ]]; then
    echo 'MISSING SHARED LIB' >&2
    exit 255
else
    main "${@}"
fi

