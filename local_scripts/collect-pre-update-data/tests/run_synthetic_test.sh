#!/usr/bin/env bash

# collect-pre-update-data synthetic tests automation


: ${DATA_DIR:=/porta_var/update/collect_pre_update_data}

declare -gA COLORS
COLORS[GREEN]='\e[92m'
COLORS[RED]='\e[91m'
COLORS[RESET]='\e[0m'

USE_COLORS=false


# Runtime variables, don't touch
EXIT_CODE=0
CPUD_EXEC=
BACKUP_ID=

set -o errexit
set -o pipefail

MY_PATH=$(readlink -f ${0})
MY_NAME=${MY_PATH##*/}
MY_BASEPLACE=${MY_PATH%/*}



msg_info() {
    local msg=${1:?'message to log is required'}
    ${USE_COLORS} \
    && echo -e "${COLORS['GREEN']}\n\n\n${msg}\n\n\n${COLORS['RESET']}" >&2 \
    || echo -e "\n\n\n!!! IMPORTANT INFO: ${msg}\n\n\n" >&2
}

msg_error() {
    local msg=${1:?'message to log is required'}
    ${USE_COLORS} \
    && echo -e "${COLORS['RED']}\n\n\n${msg}\n\n\n${COLORS['RESET']}" >&2 \
    || echo -e "\n\n\n!!! IMPORTANT ERROR: ${msg}\n\n\n" >&2
}

set_code() {
    local code=${1:?'error code to set is required'}
    local msg=${2}

    if [[ -n ${msg} ]]; then
        [[ ${code} -eq 0 ]] \
        && msg_info "${msg}" \
        || msg_error "${msg}"
    fi
    EXIT_CODE=${code}
}



test_cpud() {
    local mode=${1?'CPUD mode to execute is required'}
    local cpud_args=${2:?'CPUD mode arguments are required'}
    local diff_args=${3:?'diff arguments are required'}

    msg_info "Starting CPUD in ${mode} mode"

    ${CPUD_EXEC} -d -np ${mode} ${cpud_args} \
    && msg_info "CPUD in ${mode} mode finished without issues; checking diff" \
    || set_code 1 "CPUD failed in ${mode} mode"

    diff -u ${diff_args} \
    && msg_info "No unexpected ${mode} mode diff found" \
    || set_code 1 "Got unexpected ${mode} mode diff"

    BACKUP_ID=$((BACKUP_ID + 1))
}


test_pc_mods_parser() {
    local fc_synthetic=${MY_BASEPLACE}/check_patches_f.collected.synthetic.txt
    local fc_expected=${MY_BASEPLACE}/check_patches_f.parsed.expected.txt
    local fc_real="${DATA_DIR}/backup_${BACKUP_ID}/raws/check_patches_f.parsed.*.txt"

    test_cpud check-patches-f \
        "-fc ${fc_synthetic}" \
        "${fc_expected} ${fc_real}"
}

test_pi_mods_parser() {
    local fp_synthetic=${MY_BASEPLACE}/patches_inventory.collected.synthetic.txt
    local fp_expected=${MY_BASEPLACE}/patches_inventory.parsed.expected.txt
    local fp_real="${DATA_DIR}/backup_${BACKUP_ID}/raws/patches_inventory.parsed.*.txt"

    test_cpud patches-inventory \
        "-fp ${fp_synthetic}" \
        "${fp_expected} ${fp_real}"
}

test_mods_reporter() {
    local fc_synthetic=${MY_BASEPLACE}/check_patches_f.collected.synthetic.txt
    local fp_synthetic=${MY_BASEPLACE}/patches_inventory.collected.synthetic.txt
    local report_expected=${MY_BASEPLACE}/mods_reporter.compact.expected.txt
    local report_real="${DATA_DIR}/backup_${BACKUP_ID}/reports/mods_reporter.compact.*.txt"

    test_cpud mods-reporter \
        "-na -nd -a -fc ${fc_synthetic} -fp ${fp_synthetic}" \
        "${report_expected} ${report_real}"
}



warn_about_limitations() {
    cat <<README >&2
Note, these tests purposes are:
1. Test whether PCModsParser and PIModsParser correctly process data.
2. Test whether ModsProvider inheritors correctly form index.
3. Test whether ModsReporter correctly operates with from ModsProvider.

Note, these tests don't include:
1. ModifiedFile RPM owner resoluion at the end of PCModsParser execution.
2. Details retrieval during ModsReporter execution.
3. Sender execution with email receiving in YouTrack.
4. Hardware and network checks/backups.

These are limitations that come either due to necessity to have servers
in the corresponding state, or due to components simplicity.

README
}


set_cpud_paths() {
    CPUD_EXEC=${MY_BASEPLACE}/../cpud.py

    [[ -x ${CPUD_EXEC} ]] \
    || {
        set_code 1 'CPUD main executable is unreachable'
        exit ${EXIT_CODE}
    }
}

set_backup_id() {
    BACKUP_ID=$(
        find ${DATA_DIR} -maxdepth 1 -type d -name 'backup_*' \
        | sort -nr | head -1 | awk -F'_' '{print $NF}' || true
    )
    [[ -n ${BACKUP_ID} ]] \
    && BACKUP_ID=$((BACKUP_ID + 1)) \
    || BACKUP_ID=1
}



main() {
    warn_about_limitations

    set_cpud_paths
    set_backup_id

    test_pc_mods_parser
    test_pi_mods_parser
    test_mods_reporter

    exit ${EXIT_CODE}
}


main

