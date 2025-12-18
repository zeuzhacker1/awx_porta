#!/usr/bin/env python3

import subprocess
import json
import os
import gzip
import bz2
import io

cmet = {}
cmet['1270'] =['add_callqueue','add_customer_huntgroup','get_account_huntgroups_list','get_callqueue_info','get_callqueue_list','get_huntgroup_info','get_huntgroup_list','sync_exchange_rates','update_callqueue','update_customer_huntgroup','update_template_data_field_list']
cmet['1260'] =['add_callqueue','add_customer','add_customer_huntgroup','add_product','add_sim_card','add_subreseller','get_account_huntgroups_list','get_account_info','get_callqueue_info','get_callqueue_list','get_customer_info','get_customer_list','get_huntgroup_info','get_huntgroup_list','get_my_info','get_product_info','get_product_list','get_session_data','get_simple_account_info','get_sip_calls_list','get_ui_plugins_config','make_request','originate_advanced_call','play_prompt','start_dtmf_detect','stop_dtmf_detect','stop_play_prompt','transfer_call','update_callqueue','update_customer','update_customer_huntgroup','update_product','update_sim_card','update_template_data_field_list','validate_customer_info']
cmet['1251'] =['add_customer','add_sim_card','add_subreseller','get_account_info','get_customer_info','get_customer_list','get_my_info','get_simple_account_info','get_ui_plugins_config','make_request','update_customer','update_sim_card','update_template_data_field_list','validate_customer_info']
cmet['1250'] =['add_customer','add_service','add_subreseller','get_brand_panel_info','get_discount_plan_list','update_customer','update_template_data_field_list','validate_customer_info']
cmet['1241'] =['get_brand_panel_info','get_ui_plugins_config','make_request']
cmet['1240'] =['add_vd_threshold','get_discount_plan_list','get_ui_plugins_config','get_vd_threshold_info','get_vd_threshold_list','make_request','update_vd_threshold']
cmet['1231'] =['get_brand_panel_info','get_discount_plan_list']
cmet['1230'] =['add_price_selection','get_customer_xdrs','get_xdr_list']
cmet['1221'] =['add_price_selection','get_customer_xdrs','get_xdr_list']
cmet['1220'] =['add_options_template','add_price_selection','add_rate','get_price_selection_info','get_rate_info','get_taxation_info','update_options_template','update_taxation']
cmet['1211'] =['add_price_selection','add_rate','get_price_selection_info','get_rate_info']
cmet['1210'] =['add_options_template','add_service','add_subscription','get_phone_directory_list','get_price_selection_list','get_rate_list','update_options_template','update_subscription']
cmet['1206'] =['add_customer','add_sim_card','add_subreseller','get_account_info','get_customer_info','get_customer_list','get_my_info','get_simple_account_info','update_customer','update_sim_card','update_template_data_field_list','validate_customer_info']
cmet['1205'] =['get_ui_plugins_config','make_request']
cmet['1204'] =['get_brand_panel_info','get_discount_plan_list']
cmet['1203'] =['add_price_selection','get_customer_xdrs','get_xdr_list']
cmet['1201'] =['add_options_template','add_price_selection','add_rate','add_subscription','get_price_selection_info','get_rate_info','update_options_template','update_subscription']
cmet['1200'] =['add_customer_individual','add_service','get_phone_directory_list','get_price_selection_list','get_rate_list','get_service_list','update_customer_individual']
cmet['1191'] =['add_customer_individual','add_service','update_customer_individual']
cmet['1190'] =['add_phonebook_record','add_rate','add_subscription','add_tariff','add_user','delete_on_spot_conference_participant','get_abbreviated_dialing_number_list','get_access_number_info','get_access_number_list','get_access_policy_info','get_access_policy_list','get_access_role_info','get_access_role_list','get_account_followme','get_account_info','get_active_calls_list','get_active_sessions_list','get_assigned_commitment_record_info','get_assigned_commitment_record_list','get_assigned_commitment_terms','get_attribute_list','get_card_info','get_card_list','get_cc_staff_info','get_cc_staff_list','get_commitment_info','get_commitment_list','get_connection_destination_group_list','get_customer_class_info','get_customer_class_list','get_customer_info','get_customer_list','get_customer_numbers','get_dest_group_info','get_dest_group_list','get_dest_group_set_list','get_dialing_rule_info','get_dialing_rule_list','get_did_group_list','get_discount_plan_info','get_discount_plan_list','get_env_info','get_env_list','get_marketing_group_info','get_marketing_group_list','get_metric_charge_methods_list','get_my_info','get_notification_category_list','get_notification_list','get_number_info','get_on_spot_conference_participant_list','get_owner_batch_info','get_owner_batch_list','get_product_discount_plan_list','get_product_info','get_product_info_detailed','get_product_list','get_product_list_detailed','get_rate_info','get_rate_list','get_rating_group_info','get_rating_group_list','get_route_category_info','get_route_category_list','get_rp_category_list','get_service_policy_info','get_service_policy_list','get_simple_account_info','get_subscription_info','get_subscription_list','get_subscriptions','get_tax_transaction_code_info','get_tax_transaction_code_list','get_taxation_info','get_ua_info','get_ua_list','get_ua_profile_info','get_ua_profile_list','get_ua_profile_metainfo','get_ua_type_list','get_user_info','get_user_list','get_vd_notification_list','get_vendor_batch_info','get_vendor_batch_list','join_on_spot_conference','match_destination_groups','originate_advanced_call','update_account_followme','update_on_spot_conference_participant','update_phonebook_record','update_rate','update_subscription','update_taxation','update_user','upload','validate_customer_info']
cmet['1181'] =['add_customer_individual','add_tariff','get_account_info','get_customer_info','get_my_info','update_customer_individual']
cmet['1180'] =['add_account','add_account_with_topup','add_discount_plan','add_netnumber_info','add_node','add_phonebook_record','add_representative','add_subscription','disable_api_notifications','enable_api_notifications','get_access_number_list','get_account_info','get_account_product_info','get_accounts_subscriptions','get_allowed_addons','get_discount_plan_info','get_discount_plan_list','get_ivr_application_list','get_node_info','get_node_list','get_number_info','get_number_list','get_payment_method_info','get_product_discount_plan_list','get_product_info','get_product_list','get_simple_account_info','get_sip_calls_list','get_subscription_info','get_subscription_list','get_subscriptions','make_transaction','obtain_access_number','obtain_number','release_access_number','update_account','update_discount_plan','update_node','update_payment_method','update_phonebook_record','update_representative','update_subscription','validate_account_info','vd_topup']
cmet['1171'] =['add_phonebook_record','add_representative','get_account_info','get_customer_info','get_my_info','update_phonebook_record','update_representative']
cmet['1170'] =['update_number_list']
cmet['1161'] =['update_number_list']
cmet['1160'] =['add_rate','add_rate_group','batch_add_rate','disconnect_session','get_card_list','send_to_rt','update_rate','update_rate_group','void_invoice_list']
cmet['1156'] =['add_subscription','update_subscription']
cmet['1155'] =['add_service']
cmet['1153'] =['add_phonebook_record','add_representative','get_account_info','get_customer_info','get_my_info','update_phonebook_record','update_representative']
cmet['1152'] =['update_number_list']
cmet['1151'] =['void_invoice_list']
cmet['1150'] =['add_rate','add_rate_group','add_service_and_rating','batch_add_rate','send_to_rt','update_rate','update_rate_group']
cmet['1141'] =['add_rate','add_rate_group','batch_add_rate','update_rate','update_rate_group','void_invoice_list']
cmet['1131'] =['add_discount_plan','update_discount_plan']
cmet['1130'] =['add_customer','add_customer_individual','add_subreseller','update_customer','update_customer_individual']
cmet['1121'] =['add_subreseller','add_customer','add_customer_individual','update_customer','update_customer_individual','add_discount_plan','update_discount_plan']
cmet['1120'] =['make_transaction']
cmet['1111'] =['add_subreseller','update_account','update_accounts_batch']
cmet['1110'] =['assign_sim_card','estimate_taxes','get_card_info','get_card_list','get_config_data','get_invoice_list','release_sim_card','update_account','update_sim_card','update_sim_card_list']
cmet['1105'] =['add_rate','add_rate_group','batch_add_rate','update_rate','update_rate_group','void_invoice_list']
cmet['1102'] =['add_customer','add_customer_individual','add_subreseller','update_customer','update_customer_individual']
cmet['1101'] =['update_account','update_accounts_batch']
cmet['1100'] =['estimate_taxes']
cmet['1091'] =['estimate_taxes','update_account']
cmet['1090'] =['update_did_provider_account','add_did_provider_account']
cmet['1081'] =['update_did_provider_account','add_did_provider_account']
cmet['1071'] =['update_did_provider_account','add_did_provider_account']
cmet['1070'] =['add_customer','add_subreseller','change_password','estimate_taxes','get_pay_required_invoices_summary','update_customer','update_user','validate_customer_info']
cmet['1061'] =['change_password','update_user']
cmet['1060'] =['add_account','estimate_taxes']
cmet['1056'] =['update_account','update_accounts_batch']
cmet['1055'] =['estimate_taxes','update_account']
cmet['1052'] =['change_password','update_user']
cmet['1051'] =['add_account','estimate_taxes']
cmet['1050'] =['delete_number_list','get_number_list','get_vendor_batch_info','get_vendor_batch_list','update_number_list']
cmet['1040'] =['delete_number_list','get_number_list','get_vendor_batch_info','get_vendor_batch_list','update_number_list']
cmet['1031'] =['apply_invoice_adjustment','update_taxation','get_taxation_info']
cmet['1020'] =['generate_aliases','get_customer_numbers','get_number_info','release_number','reserve_number']
cmet['1011'] =['reserve_number','release_number','get_number_info','get_customer_numbers']
cmet['1010'] =['jwt_login','jwt_login_to_realm','refresh_json_access_token','get_json_access_token_lifetime','login','login_to_realm']
cmet['1006'] =['add_account']
cmet['1001'] =['jwt_login','jwt_login_to_realm','refresh_json_access_token','get_json_access_token_lifetime','login','login_to_realm','reserve_number','release_number','get_number_info','get_customer_numbers']
cmet['990'] =['send_to_rt']
cmet['981'] =['send_to_rt']
cmet['971'] =['send_to_rt']
cmet['970'] =['get_customer_info','refresh_jwt_token','jwt_login']
cmet['961'] =['refresh_jwt_token','jwt_login']
cmet['960'] =['get_trace_session_list','get_areas_list','get_numbers_list','provision_number','originate_transaction']
cmet['953'] =['send_to_rt']
cmet['951'] =['get_trace_session_list']
cmet['941'] =['get_trace_session_list']
cmet['920'] = ['get_subscriptions','add_subscription','get_subscription_info','get_subscription_list','update_subscription','add_product','update_product','update_custom_fields_values']
cmet['910'] = ['get_processor','list_processors','get_payment_methods_for_owner']
cmet['905'] = ['get_trace_session_list']
cmet['901'] = ['get_processor','list_processors','get_payment_methods_for_owner']
cmet['900'] = ['get_ua_info']
cmet['891'] = ['add_account','update_account']
cmet['890'] = ['void_invoice','add_subscription','get_subscription_info','get_subscription_list','update_subscription','terminate_assigned_commitment_record']
cmet['881'] = ['add_account','update_account']
cmet['880'] = ['assign_commitment']
cmet['871'] = ['assign_commitment']
cmet['860'] = ['assign_commitment']
cmet['854'] = ['add_account','update_account']
cmet['850'] = ['terminate_customer']
cmet['841'] = ['terminate_customer','get_notification_category_list']
cmet['831'] = ['terminate_customer','get_notification_category_list']
cmet['830'] = ['get_ui_config_list','update_ui_config_list']
cmet['810'] = ['get_customer_info','get_customer_list']
cmet['804'] = ['get_notification_category_list','terminate_customer']
cmet['800'] = ['get_custom_report_result_list']
cmet['791'] = ['get_custom_report_result_list']
cmet['790'] = ['add_rate','add_rate_group','batch_add_rate','update_rate','update_rate_group']
cmet['781'] = ['add_topup_option','add_rate','add_rate_group','batch_add_rate','update_rate','update_rate_group']
cmet['780'] = ['add_customer','add_subreseller','get_customer_info','get_customer_list','update_customer','validate_customer_info','get_my_info']
cmet['771'] = ['add_topup_option']
cmet['770'] = ['make_transaction','get_operation_access_id','create_otp','verify_otp','add_customer_class','get_customer_class_info','get_customer_class_list','get_default_customer_class','get_extended_data_list']
cmet['760'] = ['make_transaction','get_operation_access_id','create_otp','verify_otp']
cmet['753'] = ['add_topup_option','add_rate_group','batch_add_rate','update_rate','update_rate_group']
cmet['751'] = ['make_transaction','get_operation_access_id','create_otp','verify_otp']
cmet['750'] = ['clone_customer_class']
cmet['740'] = ['add_connection','get_connection_list','update_connection','get_request_list','get_extended_data_list','update_customer','get_customer_info','add_customer','add_subreseller','get_customer_info','get_customer_list','get_spending_plan_counter_info','get_spending_plan_counter_list','add_spending_plan_counter','update_spending_plan_counter','add_customer_class','get_customer_class_info','get_customer_class_list','update_customer_class','get_spending_plan_list','get_spending_plan_info','add_spending_plan','update_spending_plan','delete_spending_plan','get_spend_constraint_list','get_spend_constraint_info','add_spend_constraint','get_spend_constraint_limit_list','get_spend_constraint_limit_info','add_spend_constraint_limit','get_fraud_traffic_profile_list','get_fraud_traffic_profile_info','add_fraud_traffic_profile','update_fraud_traffic_profile','delete_fraud_traffic_profile','add_constraint','update_constraint','delete_constraint','assess_traffic','get_constraint_list','get_traffic_alert_list']
cmet['731'] = ['get_customer_list']
cmet['730'] = ['upload_emergency_units','upload','upload_dest_group_set','upload_did_numbers','revert_xdr_list','update_number_list','delete_number_list','regenerate_invoice_list','upload_sim_cards','get_exchange_rate_list','get_spending_plan_counter_info','add_roaming_profile','update_roaming_profile','get_account_state','login','ping','reset_password','logout','assign_sim_card','add_connection','get_connection_info','get_connection_list','update_connection','get_request_list']
cmet['721'] = ['get_exchange_rate_list','get_spending_plan_counter_info','add_roaming_profile','update_roaming_profile','get_account_state','assign_sim_card','add_connection','update_connection','get_connection_list','get_connection_info','get_request_list']
cmet['720'] = ['get_rate_list','search_rate_list','add_subreseller','add_customer','update_customer','get_xdr_list','estimate_call_price','get_web_log_list','delete_tariff','get_subscriptions','add_subscription','update_subscription','close_subscription','delete_subscription','activate_subscriptions','upload_emergency_units','upload','upload_dest_group_set','upload_did_numbers','revert_xdr_list','update_number_list','delete_number_list','regenerate_invoice_list','upload_sim_cards']
cmet['711'] = ['get_xdr_list','estimate_call_price','get_web_log_list','delete_tariff','get_subscriptions','add_subscription','update_subscription','close_subscription','delete_subscription','activate_subscriptions','upload_emergency_units','upload','upload_dest_group_set','upload_did_numbers','revert_xdr_list','update_number_list','delete_number_list','regenerate_invoice_list','upload_sim_cards','get_exchange_rate_list','get_spending_plan_counter_info','add_roaming_profile','update_roaming_profile','get_account_state']
cmet['710'] = ['get_payment_transaction_list','get_ua_profile_list','get_subscription_list','get_xdr_list','get_tsransactions_total_info','get_web_log_list','get_rate_list','search_rate_list','search_rate_list','add_customer','add_subreseller','update_customer']
cmet['703'] = ['assign_sim_card','get_connection_info','update_connection','add_connection','get_connection_list','get_request_list']
cmet['702'] = ['delete_tariff','get_subscriptions','add_subscription','update_subscription','close_subscription','delete_subscription','activate_subscriptions','upload_emergency_units','upload_dest_group_set','upload_did_numbers','upload','revert_xdr_list','update_number_list','delete_number_list','regenerate_invoice_list','upload_sim_cards','get_exchange_rate_list','get_spending_plan_counter_info','add_roaming_profile','update_roaming_profile','get_account_state']
cmet['701'] = ['get_subscription_list','get_xdr_list','get_tsransactions_total_info','get_web_log_list','get_rate_list','search_rate_list','search_rate_list','add_subreseller','update_customer','add_user','update_user','get_xdr_list','estimate_call_price','get_web_log_list']
cmet['700'] = ['get_product_list','add_service_policy','update_service_policy','get_attribute_list','get_service_policy_list','get_rate_list','add_service','get_service_info','  get_service_list','update_service',' add_service_pool',' get_service_pool_info',' get_service_pool_list',' get_custom_fields_schema',' logout',' add_tariff',' update_tariff',' get_tariff_info',' get_tariff_list',' test_translation_rule',' add_account',' update_account',' validate_account_info',' add_customer',' update_customer',' validate_customer_info',' add_subreseller',' get_active_sessions_list',' get_payment_transaction_list',' get_ua_profile_list','add_product','get_account_product_info','get_product_info','get_product_list','update_product','get_allowed_addons']
cmet['691'] = ['add_account','add_customer','add_group','add_merchant','add_number','add_product','add_service_policy','add_subreseller','add_tariff','arrange_policies_priority','cancel_did_assignment','get_access_role_list','get_account_product_info','get_active_sessions_list','get_allowed_addons','get_attribute_list','get_custom_fields_schema','get_customer_xdrs','get_dest_group_set_info','get_dest_group_set_list','get_destination_list','get_dialing_rule_info','get_dialing_rules_list','get_discount_plan_info','get_discount_plan_list','get_group_list','get_invoice_list','get_ivr_application_info','get_ivr_application_list','get_number_list','get_payment_transaction_list','get_product_info','get_product_list','get_rate_list','get_service_policy_info','get_service_policy_list','get_subscription_list','get_tariff_info','get_tariff_list','get_taxation_info','get_template_list','get_tsransactions_total_info','get_ua_profile_list','get_vendor_batch_list','get_xdr_list','logout','review_invoice','test_translation_rule','update_account','update_customer','update_group','update_product','update_service_policy','update_tariff','update_taxation','validate_account_info','validate_customer_info']
cmet['690'] = ['add_customer_class','add_group','add_routing_plan','add_service_policy','add_user','assign_did_to_owner_batch','get_attribute_list','get_call_barring_class_list','get_connection_info','get_connection_list','get_custom_field_info','get_custom_field_list','get_customer_class_info','get_customer_class_list','get_customer_info','get_customer_list','get_customer_xdrs','get_destination_list','get_generated_xdrs_file','get_number_list','get_payment_transaction_list','get_processor','get_product_list','get_routing_plan_info','get_routing_plan_list','get_service_policy_info','get_service_policy_list','get_sip_call_list','get_sip_status','get_subscription_list','get_subscriptions','get_tax_plugin','get_tax_plugins_list','get_tax_transaction_code_list','get_user_info','get_user_list','get_xdr_list','list_processors','make_tax_transaction','make_transaction','originate_advanced_call','review_invoice_list','update_customer_class','update_group','update_routing_plan','update_service_policy','update_user']
cmet['681'] = ['add_customer_class','add_group','add_routing_plan','add_user','assign_did_to_owner_batch','cancel_did_assignment','get_call_barring_class_list','get_connection_info','get_connection_list','get_custom_field_info','get_custom_field_list','get_custom_fields_schema','get_customer_class_info','get_customer_class_list','get_destination_list','get_number_list','get_payment_transaction_list','get_product_list','get_routing_plan_info','get_routing_plan_list','get_subscriptions','get_tax_plugin','get_tax_plugins_list','get_tax_transaction_code_list','get_template_list','get_user_info','get_user_list','get_vendor_batch_list','get_xdr_list','make_tax_transaction','make_transaction','review_invoice','review_invoice_list','update_customer_class','update_group','update_routing_plan','update_user','get_customer_xdrs']
cmet['680'] = ['get_transactions_total_info','get_invoice_info','get_invoice_list','add_customer','update_customer','validate_customer_info','add_subreseller','update_env','add_representative','update_representative','add_authz_rule','update_authz_rule','get_authz_rule_list','get_customer_info','get_customer_list','originate_advanced_call','list_processors','get_processor','get_generated_xdrs_file','get_customer_xdrs','get_xdr_list','get_subscriptions','add_routing_plan','update_routing_plan','get_routing_plan_info','get_routing_plan_list','get_destination_list','get_subscription_list','get_discount_info','get_discount_list','add_discount','update_discount']
cmet['671'] = ['add_discount','add_routing_plan','add_user','assign_did_to_owner_batch','get_customer_info','get_customer_list','get_destination_list','get_discount_info','get_discount_list','get_invoice_info','get_invoice_list','get_payment_transaction_list','get_processor','get_routing_plan_info','get_routing_plan_list','get_subscription_list','get_subscriptions','get_transactions_total_info','get_user_info','get_user_list','list_processors','review_invoice_list','update_discount','update_routing_plan','update_user']
cmet['670'] = ['add_customer_class','add_discount_plan','add_owner_batch','add_product','add_subscription','add_tariff','add_ua','add_ua_profile','assign_did_to_owner_batch','delete_account','generate_ua_profile','get_account_info','get_account_list','get_custom_field_list','get_customer_class_info','get_customer_class_list','get_customer_list','get_discount_plan_info','get_discount_plan_list','get_invoice_info','get_invoice_list','get_number_info','get_payment_method_info','get_product_info','get_product_list','get_request_info','get_request_list','get_routing_plan_info','get_routing_plan_list','get_service_features_list','get_subscription_info','get_subscription_list','get_tariff_info','get_tariff_list','get_ua_info','get_ua_list','get_ua_profile_info','get_ua_profile_list','get_ua_type_list','login','make_transaction','topup_account','update_account','update_customer_class','update_discount_plan','update_owner_batch','update_payment_method','update_product','update_subscription','update_tariff','update_ua','update_ua_profile','validate_account_info','vd_topup','get_user_info','get_user_list']
cmet['661'] = ['add_discount','add_owner_batch','add_ua_profile','assign_did_to_owner_batch','generate_ua_profile','get_account_info','get_account_list','get_custom_field_list','get_customer_class_list','get_discount_info','get_discount_list','get_invoice_info','get_invoice_list','get_number_info','get_payment_method_info','get_routing_plan_info','get_routing_plan_list','get_service_features_list','get_transactions_total_info','get_ua_info','get_ua_list','get_ua_profile_info','get_ua_profile_list','get_ua_type_list','get_user_info','get_user_list','login','make_transaction','set_callqueue_moh_file','topup_account','update_account','update_discount','update_owner_batch','update_ua_profile','validate_account_info']
cmet['660'] = ['get_customer_list','add_criterion','update_criterion','make_transaction','get_ua_profile','update_ua_profile','get_ua_list','get_ua_info','get_active_calls_list','get_invoice_list','get_invoice_info','get_request_info','get_request_list','vd_topup','get_payment_method_info','update_payment_method','update_account','delete_account']
cmet['656'] = ['add_sim_card','generate_accounts','get_active_sessions_list','get_alias_list','get_currency_list','get_customer_xdrs','get_huntgroup_info','get_huntgroup_list','get_payment_transaction_list','get_rate_list','get_roaming_country_list','get_template_scoped_list','get_xdr_list','search_rate_list']
cmet['655'] = ['add_account','add_customer','add_group','add_merchant','add_number','add_subreseller','get_access_role_list','get_active_sessions_list','get_dest_group_set_info','get_dest_group_set_list','get_discount_plan_info','get_discount_plan_list','get_group_list','get_invoice_list','get_ivr_application_info','get_ivr_application_list','get_number_list','get_payment_transaction_list','get_product_list','get_subscription_list','get_taxation_info','get_ua_profile_list','logout','test_translation_rule','update_account','update_customer','update_group','update_taxation','validate_account_info','validate_customer_info']
cmet['654'] = ['add_callqueue','add_customer_class','add_group','cancel_did_assignment','get_call_barring_class_list','get_connection_info','get_connection_list','get_custom_field_info','get_custom_field_list','get_custom_fields_schema','get_customer_class_info','get_customer_class_list','get_destination_list','get_number_list','get_payment_transaction_by_id','get_payment_transaction_list','get_tax_plugin','get_tax_plugins_list','get_tax_transaction_code_list','get_template_list','get_vendor_batch_list','get_xdr_list','make_tax_transaction','make_transaction','register_transaction','review_invoice','update_callqueue','update_customer_class','update_group','get_customer_xdrs']
cmet['653'] = ['add_routing_plan','add_user','assign_did_to_owner_batch','get_customer_info','get_customer_list','get_destination_list','get_invoice_list','get_payment_transaction_list','get_processor','get_routing_plan_info','get_routing_plan_list','get_subscription_list','get_subscriptions','get_user_info','get_user_list','list_processors','review_invoice_list','update_routing_plan','update_user']
cmet['652'] = ['add_discount','add_owner_batch','get_custom_field_list','get_customer_class_list','get_customer_xdrs','get_dialing_rule_list','get_discount_info','get_discount_list','get_invoice_info','get_invoice_list','get_number_info','get_payment_method_info','get_route_category_info','get_route_category_list','get_routing_criteria_list','get_routing_plan_info','get_routing_plan_list','get_service_features_list','get_transactions_total_info','get_ua_list','get_ua_type_list','get_user_info','get_user_list','make_transaction','update_discount','update_owner_batch']
cmet['651'] = ['add_access_role','add_alias','add_allowed_location','add_auto_payment','add_cp_condition','add_customer_class_metric','add_customer_metric','add_customer_site','add_did_group','add_did_provider_account','add_owner_batch','add_phonebook_record','add_service','add_service_pool','add_spending_plan','add_subscription','add_ua_profile','add_vendor_batch','assign_did_to_owner_batch','assign_sim_card','assign_ua','delete_account','delete_auto_payment','delete_customer_class_metric','delete_customer_metric','delete_payment_method','delete_service','delete_subscription','generate_ua_profile','get_access_policy_info','get_access_role_info','get_access_role_list','get_access_role_type_list','get_account_info','get_account_list','get_active_calls_list','get_alias_list','get_allowed_location_list','get_auto_payment_info','get_connection_list','get_credit_limit_history','get_currency_info','get_currency_list','get_customer_class_metrics_list','get_customer_info','get_customer_list','get_customer_metrics_list','get_customer_xdrs','get_destination_list','get_dialing_rule_info','get_dialing_rules_list','get_did_group_list','get_did_provider_account_list','get_discount_info','get_discount_list','get_discount_plan_info','get_invoice_info','get_invoice_list','get_my_info','get_netaccess_usage_record_list','get_node_info','get_node_list','get_number_list','get_owner_batch_info','get_owner_batch_list','get_phonebook_list','get_phonebook_record','get_rate_list','get_request_info','get_request_list','get_service_features','get_service_info','get_service_pool_info','get_service_pool_list','get_spending_plan_counter_info','get_spending_plan_info','get_spending_plan_list','get_subscriptions','get_tariff_list','get_time_period_info','get_time_period_list','get_transactions_total_info','get_ua_info','get_ua_list','get_ua_profile','get_ua_profile_info','get_ua_profile_list','get_used_location_list','get_vendor_batch_list','get_vendor_info','get_vendor_list','get_xdr_list','make_transaction','modify_spending_limit','release_sim_card','release_ua','search_rate_list','set_callqueue_moh_file','topup_account','update_access_role','update_account','update_allowed_location','update_auto_payment','update_cp_condition','update_customer_class_metric','update_customer_metric','update_customer_site','update_did_group','update_did_provider_account','update_inventory_options','update_owner_batch','update_payment_method','update_phonebook_record','update_service','update_service_features','update_service_pool','update_spending_plan','update_subscription','update_ua_profile','update_vendor_batch','validate_account_info','validate_customer_info']
cmet['650'] = ['get_discount_plan_list','get_account_info','cancel_provision','get_areas_list','get_countries_list','get_numbers_list','get_provider_info','provision_number','get_service_pool_list','get_roaming_profile_info','get_bundle_promotion_list','add_customer','add_subreseller','get_customer_info','update_customer','validate_customer_info','get_customer_list','add_account','get_my_info','get_account_list','topup_account','update_account','validate_account_info','get_quick_form_info','get_quick_forms_list','update_quick_form','get_sip_calls_list','get_customer_xdrs','get_xdr_list','originate_call','update_cp_condition','get_cp_condition_list','delete_cp_condition','add_cp_condition']
cmet['641'] = ['update_cp_condition','get_cp_condition_list','delete_cp_condition','add_cp_condition','add_customer','update_customer','get_customer_info','get_customer_list','get_template_list','originate_call','update_number_list','get_spending_plan_list','get_spending_plan_info','get_ua_type_list','get_discount_info','add_account','add_representative','add_user','add_vendor']
cmet['640'] = ['get_service_wallet_xdr_list','get_taxation_info','update_taxation','get_customer_list','get_areas_list','get_countries_list','get_service_policy_list','get_number_list','get_subscription_list','get_subscription_info','add_subscription','update_subscription','add_rate','add_rate_group','update_rate','update_rate_group','cancel_provision','get_provider_info','provision_number','get_number_list_statistics']
cmet['631'] = ['cancel_provision','get_areas_list','get_countries_list','get_numbers_list','get_provider_info','provision_number','get_subscriptions','update_cp_condition','get_cp_condition_list','delete_cp_condition','add_cp_condition','get_number_list_statistics','get_service_policy_list','get_owner_batch_list','get_card_info','get_account_info','get_account_list','validate_account_info','add_account','update_account','topup_account','get_number_info','get_number_list','get_did_provider_account_list','get_vendor_batch_list','get_taxation_info','update_customer_class','get_customer_list','get_node_list']
cmet['630'] = ['get_number_list','get_number_info','add_number','set_account_state','estimate_taxes','get_spending_plan_list','get_card_list','get_customer_xdrs','get_xdr_list','get_account_list','get_extensions_list','add_customer_class','update_customer_class','get_default_customer_class','get_customer_class_info','get_custom_fields_schema','get_group_info','add_group','update_group','get_group_list','get_product_list','get_customer_list','get_representative_info','get_vendor_batch_list','get_owner_batch_list','get_owner_batch_info','add_representative','get_representative_list','update_representative','get_customer_class_list']
cmet['621'] = ['set_account_state','estimate_taxes','add_rate','add_rate_group','update_rate','update_rate_group','get_rate_info','get_rate_list','get_currency_info','get_currency_list','add_currency','update_currency','generate_accounts','get_tariff_info','get_tariff_list','add_tariff','update_tariff','get_account_info','get_account_list','validate_account_info','add_account','update_account','topup_account','get_taxation_info','update_taxation']
cmet['620'] = ['get_huntgroup_info','get_huntgroup_list','get_member_of_huntgroups_list','add_customer_huntgroup','update_customer_huntgroup','get_account_followme','add_followme_number','update_followme_number','get_vendor_list','get_number_list','get_number_info','add_number','get_connection_list','get_connection_info','add_connection','update_connection','add_vendor','update_vendor','get_vendor_info','get_tariff_list','get_tariff_info','add_tariff','update_tariff','get_override_tariff']
cmet['611'] = ['get_customer_class_info','get_customer_class_list','add_customer_class','update_customer_class','get_default_customer_class','get_ua_list','add_ua','set_account_state','estimate_taxes']
cmet['610'] = ['get_node_info','get_node_list','get_discount_info','get_discount_list','add_discount','update_discount','get_subscription_list','get_subscription_info','add_subscription','get_criterion','add_criterion','update_criterion','get_criteria_list','vd_topup','get_tax_plugins_list','get_taxation_info','get_sip_calls_list','make_transaction','get_full_vd_counter_info','register_transaction','get_payment_transaction_by_id','get_payment_transaction_list','get_customer_info','validate_customer_info','get_customer_list','get_my_info','add_customer','update_customer','add_subreseller','get_taxation_info','update_taxation','get_customer_class_info','get_customer_class_list','add_customer_class','update_customer_class','get_default_customer_class']
cmet['606'] = ['get_invoice_list','get_invoice_info']
cmet['605'] = ['get_node_info','get_node_list','add_account','update_account','add_customer','update_customer','add_vendor','update_vendor']
cmet['604'] = ['cancel_provision','get_areas_list','get_countries_list','get_numbers_list','get_provider_info','provision_number','get_subscriptions','update_cp_condition','get_cp_condition_list','delete_cp_condition','add_cp_condition']
cmet['603'] = ['get_extensions_list','get_customer_extension_info','estimate_taxes','get_destination_list','add_vendor','update_vendor','get_account_info','get_account_list','validate_account_info','add_account','update_account','topup_account','get_taxation_info','update_taxation']
cmet['602'] = ['add_callqueue','update_callqueue','get_callqueue_info','get_callqueue_list','add_customer_class','update_customer_class','get_customer_class_list','get_default_customer_class','get_customer_class_info','get_payment_transaction_list','get_service_type_list','get_service_list','get_service_pool_info','get_vendor_list','add_vendor','update_vendor','get_vendor_info','get_ua_list','add_ua','set_account_state','estimate_taxes','get_active_calls_list','get_extensions_list','get_customer_extension_info']
cmet['601'] = ['get_tax_plugins_list','get_taxation_info','update_taxation','get_customer_list','get_customer_info','update_customer','add_customer','validate_customer_info','get_my_info','get_account_info','get_account_list','validate_account_info','add_account','update_account','topup_account','get_sip_calls_list','get_full_vd_counter_info','vd_topup','register_transaction','get_payment_transaction_by_id','get_payment_transaction_list','get_subscriptions','add_subscription','update_subscription','get_account_product_info','get_product_info','add_product','update_product','get_allowed_addons','get_vendor_list','get_connection_list','delete_cp_rule','get_tax_plugin_codes_list','add_customer_class','update_customer_class','get_customer_class_list','get_default_customer_class','get_customer_class_info','get_user_info','get_user_list','add_user','update_user']
cmet['600'] = ['get_services_consumption','get_customer_xdrs','get_owner_batch_info','add_owner_batch','update_owner_batch','add_account','add_account_with_topup','update_account','validate_account_info','get_owner_batch_list','get_customer_info','validate_customer_info','get_customer_list','add_customer','update_customer','get_my_info','get_discount_info','get_discount_list','add_discount','update_discount']
cmet['591'] = ['get_product_list','get_service_list','get_service_pool_info','get_user_info','get_user_list','add_user','update_user','get_account_list']
cmet['590'] = ['originate_call','register_transaction','get_owner_batch_info','add_owner_batch','update_owner_batch','get_topup_option_info','get_topup_option_list','add_topup_option','update_topup_option','update_discount','add_discount','get_discount_list','get_discount_info','vd_topup']
cmet['581'] = ['get_dest_group_list','originate_call','get_owner_batch_info','add_owner_batch','update_owner_batch','vd_topup','add_account','add_account_with_topup','update_account','validate_account_info']
cmet['580'] = ['get_dialing_rules_list','get_dialing_rule_info','add_dialing_rule','update_dialing_rule','vd_topup','get_full_vd_counter_info','get_customer_info','validate_customer_info','get_customer_list','add_customer','update_customer','get_my_info','get_discount_info','get_discount_list','get_call_barring_options','get_customer_extension_info','get_countries_list','get_areas_list','get_numbers_list']
cmet['571'] = ['get_discount_info','get_discount_list','get_call_barring_options','get_dialing_rules_list','get_dialing_rule_info','add_dialing_rule','update_dialing_rule','get_dial_rule_samples','get_customer_extension_info','get_number_list','get_dest_group_list','vd_topup']
cmet['570'] = ['get_routing_plan_list','get_customer_taxation','update_taxation','get_number_list','get_xdr_list','get_customer_xdrs','make_transaction','vd_topup','get_full_vd_counter_info','get_node_list','get_node_info','get_dialing_rules_list','get_dialing_rule_info','add_dialing_rule','update_dialing_rule','get_account_list','add_subscription','get_subscription_list','get_subscription_info','update_payment_method','release_did_from_customer','add_customer_class','get_customer_class_list','get_default_customer_class','get_customer_class_info','get_account_info','validate_account_info','add_account','update_account','get_account_list','get_alias_list','add_alias','delete_alias','generate_accounts']
cmet['561'] = ['get_node_list','get_node_info','get_dialing_rules_list','get_dialing_rule_info','add_dialing_rule','update_dialing_rule','get_account_info','validate_account_info','add_account','update_account','get_account_list','get_subscription_list','get_subscription_info','add_subscription','make_transaction','update_payment_method','vd_topup','release_did_from_customer','get_xdr_list','get_customer_xdrs','get_full_vd_counter_info','get_discount_info','get_discount_list','get_call_barring_options']
cmet['560'] = ['get_invoice_info','get_invoice_list','update_notification_template','generate_out_of_turn_invoice','get_customer_list','make_transaction','add_rate','add_rate_group','update_rate','update_rate_group','get_routing_plan_list','get_taxation_info','update_taxation','get_number_list','get_customer_info','validate_customer_info','get_customer_list','add_customer','update_customer','get_my_info','get_xdr_list','get_customer_xdrs','vd_topup']
cmet['556']=['add_callqueue','update_callqueue','get_customer_list','get_my_info']
cmet['555'] = ['get_dialing_rules_list','get_dialing_rule_info','add_dialing_rule','update_dialing_rule','get_customer_list','get_tax_plugin','add_representative','update_representative','get_customer_info']
cmet['554'] = ['add_account','add_account_with_topup','update_account','validate_account_info']
cmet['553'] = ['vd_topup','get_full_vd_counter_info','get_dest_group_list']
cmet['552'] = ['vd_topup','make_transaction','update_payment_method','release_did_from_customer','get_discount_info','get_discount_list']
cmet['551'] = ['get_customer_info','validate_customer_info','get_customer_list','add_customer','update_customer','get_my_info','generate_out_of_turn_invoice','get_routing_plan_list','get_taxation_info','update_taxation','get_number_list','get_tariff_info','get_tariff_list','add_tariff','update_tariff','vd_topup','get_subscription_list','get_subscription_info','add_subscription']
cmet['550'] = ['get_customer_info','validate_customer_info','get_customer_list','add_customer','update_customer','get_my_info','get_route_list','add_customer_class','get_customer_class_list','get_default_customer_class','get_customer_class_info','get_payment_method_info','update_payment_method','make_transaction','get_payment_method_info','update_payment_method','get_metric_charge_methods_list','add_customer_metric','update_customer_metric','get_invoice_info','get_invoice_list','update_notification_template','get_transactions_total_info']
cmet['541'] = ['get_customer_info','validate_customer_info','get_customer_list','add_customer','update_customer','get_my_info','get_payment_method_info','update_payment_method','make_transaction','get_payment_method_info','update_payment_method','get_metric_charge_methods_list','add_customer_metric','update_customer_metric','get_invoice_info','get_invoice_list','update_notification_template','get_account_info','generate_out_of_turn_invoice','vd_topup','get_transactions_total_info']
cmet['540'] = ['add_customer_class','get_customer_class_info','get_customer_class_list','get_default_customer_class','list_processors','get_processor','add_account','add_customer','get_full_vd_counter_info','vd_topup','get_vendor_info','get_dialing_rules_list','add_dialing_rule','get_dialing_rule_info','get_custom_fields_schema','get_huntgroup_list','add_customer_huntgroup','update_customer_huntgroup','get_customer_info','validate_customer_info','get_customer_list','add_customer','update_customer','get_my_info','get_route_list']
cmet['531'] = ['add_customer_class','get_customer_class_list','get_default_customer_class','get_customer_class_info','add_account','add_customer','get_dialing_rules_list','get_dialing_rule_info','add_dialing_rule','get_payment_method_info','update_payment_method','make_transaction','get_payment_method_info','update_payment_method','get_account_info','get_transactions_total_info']
cmet['530'] = ['get_group_list','get_product_list','get_services_consumption','get_customer_billing_periods_history','get_account_list','get_customer_info','validate_customer_info','get_customer_list','add_customer','update_customer','get_my_info','get_quick_forms_list','get_tariff_info','get_acl_list','get_ua_list','get_batch_list','get_payment_method_info','update_payment_method','make_transaction','get_payment_method_info','update_payment_method','apply_invoice_adjustment','get_full_vd_counter_info','vd_topup','get_transactions_total_info','get_ua_info','topup_account','list_merchants','get_batch_list','get_discount_Info','get_discount_list','add_discount','update_discount','get_customer_numbers']
cmet['521'] = ['get_customer_numbers','get_acl_list','add_customer_class','get_customer_class_list','get_default_customer_class','get_customer_class_info']
cmet['520'] = ['make_transaction','get_subscriptions','add_subscription','update_subscription','get_tariff_info','get_tariff_list','add_tariff','update_tariff','get_currency_info','get_account_info','validate_account_info','get_account_list','add_account','update_account','topup_account','get_quick_forms_list','get_discount_plan_info','get_discount_plan_list','add_discount_plan','update_discount_plan','get_discount_Info','get_discount_list','add_discount','update_discount','get_customer_xdrs','get_customer_billing_periods_history','list_processors','get_processor','get_customer_info','validate_customer_info','get_customer_list','add_customer','update_customer','get_my_info','get_metric_charge_methods_list','get_customer_metrics_list','add_customer_metric','update_customer_metric']
cmet['511'] = ['make_transaction','get_tariff_info','get_tariff_list','add_tariff','update_tariff','get_account_list','get_customer_info','validate_customer_info','get_customer_list','add_customer','update_customer','get_my_info','get_acl_list']
cmet['510'] = ['get_account_list','get_xdr_list','get_alias_list','get_invoice_list','get_extensions_list','get_callqueue_list','get_huntgroup_list','get_account_aliases_list','get_customer_invoices','get_customer_numbers','get_currency_info','get_currency_list','add_currency','update_currency','get_invoice_info','Customer#get_prompt_file','estimate_taxes','get_subscriptions','add_subscription','update_subscription']
cmet['506'] = ['get_routing_plan_list']
cmet['505'] = ['get_product_list','get_account_product_info','add_product','update_product','get_allowed_addons','get_account_info','validate_account_info','get_account_list','update_account']
cmet['504'] = ['get_customer_info','get_payment_method_info','update_payment_method','make_transaction','get_payment_method_info','update_payment_method']
cmet['503'] = ['get_countries_list','get_areas_list','get_numbers_list']
cmet['502'] = ['get_acl_list','get_customer_info','validate_customer_info','get_customer_list','add_customer','update_customer','get_my_info','get_account_list']
cmet['501'] = ['get_tariff_info','get_tariff_list','add_tariff','update_tariff','get_subscriptions','add_subscription','update_subscription','make_transaction','add_account','update_account','validate_account_info','get_prompt_file','get_currency_info','get_currency_list','add_currency','update_currency']
cmet['500'] = ['get_service_features_info','get_template_list','get_vd_counter_list','get_sites','get_site_info','add_customer_site','update_customer_site','get_account_list','get_xdr_list','get_alias_list','get_invoice_list','get_extensions_list','get_callqueue_list','get_member_of_huntgroups_list','get_huntgroup_list','get_account_aliases_list','get_customer_invoices','get_customer_numbers','get_account_info','update_account','add_account','topup_account','Account#get_service_features','Account#update_service_features']
cmet['491'] = ['get_service_features_info','get_vd_counter_list','get_account_list','get_xdr_list','get_alias_list','get_invoice_list','get_extensions_list','get_callqueue_list','get_member_of_huntgroups_list','get_huntgroup_list','get_account_aliases_list','get_customer_invoices','get_customer_numbers','add_currency','update_currency','get_currency_info','get_currency_list']
cmet['490'] = ['get_customer_xdrs','get_invoice_list','add_callqueue','update_callqueue','get_callqueue_info','get_callqueue_list','get_product_info','get_allowed_addons','get_customer_list','Customer#update_taxation','update_customer']
cmet['481'] = ['get_invoice_list']
cmet['480'] = ['get_invoice_info','get_customer_xdrs','get_invoice_list','get_customer_info','add_account','update_account','get_account_info','get_account_list','generate_accounts','get_number_list']
cmet['471'] = ['add_account','update_account','get_account_info','get_account_list','generate_accounts','get_number_list']
cmet['470'] = ['update_payment_method', 'topup_account', 'Account#add_periodical_payment','Account#update_periodical_payment','Account#delete_periodical_payment','Account#get_periodical_payment_info','Account#get_periodical_payment_list','Account#get_services_consuming','get_cdrs_retail_customer','Customer#add_periodical_payment','Customer#update_periodical_payment','Customer#delete_periodical_payment','Customer#get_periodical_payment_info','Customer#get_periodical_payment_list','Customer#get_services_consuming','Customer#get_lines_activesubscriptions','get_account_info']
cmet['461'] = ['update_payment_method','topup_account','add_account','update_account','get_account_info','get_account_list','Account#generate_accounts']
cmet['460'] = ['Session#login','DiscountPlan#get_vd_threshold_list','Payment#make_transaction','ACL#','Connection#utilization_balthreshold']
cmet['452'] = ['update_account']
cmet['451'] = ['ACL#','update_payment_method']
cmet['450'] = ['get_customer_info','Customer#get_taxation_info','mark_xdr_out_of_turn','generate_out_of_turn_invoice','Connection#utilization_balthreshold','Payment#update_payment_method']
cmet['441'] = ['ACL#','get_customer_info']
cmet['440'] = ['get_customer_info','Session#logout','UA#add_ua','get_rate_list','DiscountPlan#get_discount_plan_info','get_service_features_info','get_customer_xdrs','Account#get_xdr_list','get_full_vd_counter_info','add_customer']
cmet['431'] = ['add_customer','get_customer_info']
cmet['430'] = ['get_subscription_list','Customer#get_customer_list','get_customer_info','get_extensions_list','get_full_vd_counter_info','get_huntgroup_list','generate_accounts','get_active_calls_list','get_service_features_metainfo']
cmet['410'] = ['Customer#delete_abbreviated_dialing_number','Tariff#get_tariff_info','get_account_info','DID#get_customer_numbers','get_customer_info','Customer#get_customer_list','Node#get_node_list','Product#get_priorities_list','Currency#get_currency_list','Customer#get_lines_activesubscriptions']
cmet['400'] = ['Customer#delete_abbreviated_dialing_number','get_account_info','add_account','update_account','Product#get_product_list','get_full_vd_counter_info','Customer#get_lines_activesubscriptions','customer_huntgroup','update_payment_method','Customer#get_customer_invoices','Invoice#get_invoice_info','get_services_consuming','get_conference_settings','Tariff#get_tariff_info','DID#get_customer_numbers']
cmet['391'] = ['get_xdr_list','get_full_vd_counter_info','Customer#get_lines_activesubscriptions']
cmet['390'] = ['get_invoice_info','get_cp_rule_list','get_rate_list','PerServiceInfo','ConsumedServiceInfo','Connection','get_customer_xdrs']
cmet['381'] = ['get_rate_list','get_cp_rule_list']
cmet['380'] = ['make_transaction','add_service_and_rating','update_service_and_rating','get_rate_list']
cmet['371'] = ['add_service_and_rating','update_service_and_rating']
cmet['370'] = ['get_destination_list','get_account_list','get_currency_info','huntgroup','add_customer_extension','get_extensions_list','add_vd_threshold','update_vd_threshold','update_customer_site','add_rate','extensions_info','huntgroup','add_customer_extension','get_extensions_list','add_vd_threshold','update_vd_threshold','make_transaction']
cmet['361'] = ['update_customer_site','add_customer','make_transaction']
cmet['360'] = ['get_xdr_list','get_destination_list','get_rate_list','make_transaction','add_account','update_account','add_customer_site','update_customer_site','add_discount']
cmet['350'] = ['get_account_info','update_tariff','delete_user','update_user','get_user_info','get_user_list','get_account_info','get_xdr_list','get_product_list','follow','add_customer']
cmet['341'] = ['update_tariff','get_account_info','get_xdr_list']
cmet['340'] = ['get_customer_info','get_status_history','release_ua','get_vendor_list','add_rate','get_account_info','update_user','delete_user','get_user_info','get_user_list']
cmet['331'] = ['update_service_features','get_account_info']
cmet['330'] = ['get_vd_counter_list','get_full_vd_counter_info','get_dial_rule_samples','get_customer_info','get_status_history','release_ua','get_vendor_list']
cmet['321'] = ['get_dial_rule_samples']
cmet['320'] = ['add_rate_group','get_rate_info','get_number_list','get_number_info','get_active_calls_list','close_subscription']
cmet['311'] = ['add_rate_group','get_number_list','get_number_info','get_active_calls_list','close_subscription']
cmet['310'] = ['make_transaction','update_customer','get_customer_xdrs','get_extensions_list','get_number_list']
cmet['304'] = ['get_account_info']
cmet['303'] = ['get_customer_info','add_rate']
cmet['301'] = ['update_account_followme','get_number_list','add_rate_group','get_number_list','get_number_info','add_periodical_payment','close_subscription']
cmet['300'] = ['update_customer','register_transaction']
cmet['291'] = ['get_periodical_payment_info','update_account','update_periodical_payment']
cmet['290'] = ['get_periodical_payment_info','update_periodical_payment','add_periodical_payment','get_services_consuming','Customer#','payment_info','add_customer','update_customer','add_alias','get_abbr_dial_list','get_service_list','topup_account']
cmet['280'] = ['get_service_info','get_service_list','get_discount_plan_list','get_account_info','get_vendor_batch_list','get_abbr_dial_list','payment_method_info','get_phonebook_list','get_customer_xdrs','get_customer_cdrs','get_cdrs_retail_customers','get_cdrs_retail_customer']
cmet['271'] = ['get_customer_xdrs']
cmet['270'] = ['get_customer_xdrs','get_customer_cdrs','get_cdrs_retail_customer','get_vendor_batch_list','get_number_info','get_account_info','get_customer_info','DID#','update_override_tariff']
cmet['261'] = ['get_tariff_info','update_override_tariff','add_abbreviated_dialing_number']
cmet['260'] = ['get_customer_info','add_customer','update_customer','validate_customer_info','add_account','update_account','add_account_with_top','validate_account_info','get_product_info','update_account','get_vendor_batch_list']
cmet['251'] = ['get_customer_info','add_customer','update_customer','validate_customer_info','add_account','update_account','add_account_with_top','validate_account_info','get_product_info','update_account']
cmet['250'] = ['update_payment_method','add_cp_rule','update_cp_rule']
cmet['242'] = ['get_customer_info','add_customer','update_customer','validate_customer_info','add_account','update_account','add_account_with_top','validate_account_info','get_product_info','update_account','add_cp_rule','update_cp_rule']
cmet['241'] = ['move_account','update_abbreviated_dialing_number','update_payment_method']
cmet['240'] = ['add_followme_number','update_followme_number']
cmet['233'] = ['move_account','add_followme_number','update_followme_number']
cmet['231'] = ['Account#','update_abbreviated_dialing_number','followme_info','update_taxation','get_xdr_list','add_account','move_account']
cmet['230'] = ['add_account','update_cp_rule','ACL#','add_customer','update_customer']
cmet['225'] = ['move_account','update_abbreviated_dialing_number']
cmet['224'] = ['add_followme_number','update_followme_number']
cmet['223'] = ['update_abbreviated_dialing_number','followme_info','update_taxation']
cmet['222'] = ['add_account','move_account','add_account','update_cp_rule','ACL#','add_customer','update_customer']
cmet['221'] = ['add_account','assign_ua','get_ua_list']
cmet['220'] = ['add_account','update_account','add_customer','update_customer','release_number','get_customer_info','make_transaction','get_xdr_list']
cmet['213'] = ['add_account']
cmet['212'] = ['assign_ua','get_ua_list','add_account','update_account','add_customer','update_customer','release_number']
cmet['211'] = ['add_account','add_customer','get_customer_info','make_transaction','update_customer','get_number_info','update_account','get_account_info','get_account_list']
cmet['210'] = ['add_account','get_product_info','make_transaction','get_account_alias_list']
cmet['206'] = ['followme_info','update_taxation']
cmet['205'] = ['update_cp_rule','ACL#','add_account']
cmet['204'] = ['get_ua_list','get_number_info']
cmet['203'] = ['release_number','add_account','add_customer','get_customer_info']
cmet['202'] = ['make_transaction','get_xdr_list','get_product_info','make_transaction','get_account_alias_list']
cmet['193'] = ['get_product_info','get_account_alias_list']
cmet['192'] = ['get_payment_method_info','delete_alias','terminate_account','add_customer','get_customer_info','update_account','get_payment_method']
cmet['190'] = ['get_account_info','move_account']
cmet['183'] = ['update_account','get_payment_method']
cmet['182'] = ['make_transaction']

def get_methods_in_range(mrfrom, mrto):
    affected_list = []
    for release in cmet:
        reln = int(release)
        if reln > mrfrom and reln <= mrto:
            affected_list.extend(cmet[release])
    affected_list = list(set(affected_list))
    affected_list.sort()
    return affected_list


if __name__ == '__main__':
    LOGPATH = '/porta_var/{{ portaadmin_ip }}/log'
    installation_hosts = subprocess.getoutput(
        "grep porta-configurator /etc/hosts | awk '{print $1}' | sort | uniq").split('\n')
    current_release = int(subprocess.getoutput("rpm -q --queryformat '%{VERSION}' porta-common").replace('.', ''))
    target_release = int({{target_release}})
    result_list = {}

    affected_list = get_methods_in_range(current_release, target_release)

    loglist = []
    totalentry = [None, None]

    fpaths = []
    for fname in os.listdir(LOGPATH):
        if 'httpd-access-web.log.1.' in fname:
            fpath = os.path.join(LOGPATH, fname)
            fpaths.append([fpath])

    second_log = ''
    if fpaths:
        second_log = fpaths[0][0]
        mtime = os.path.getmtime(fpaths[0][0])
        for fpath in fpaths:
            cur_mtime = os.path.getmtime(fpath[0])
            if cur_mtime > mtime:
                second_log = fpath[0]
                mtime = cur_mtime

        fformat = second_log.split('.')[-1]
        if fformat.startswith('gz'):
            loglist.append(gzip.GzipFile(second_log, mode='rb'))
        elif fformat.startswith('bz2'):
            loglist.append(bz2.BZ2File(second_log, mode='rb'))

    loglist.append(open(os.path.join(LOGPATH, 'httpd-access-web.log'), 'rb'))

    for f in loglist:
        text_wrapper = io.TextIOWrapper(f, encoding='utf-8', errors='replace')
        for line in text_wrapper:
            try:
                linedate = line.split(' ')[3].replace('[', '')
            except:
                continue

            if totalentry[0] is None:
                totalentry[0] = linedate
            totalentry[1] = linedate

            skip_line = not ('/soap' in line or '/rest' in line)
            for ip in installation_hosts:
                if line.startswith('{} '.format(ip)):
                    skip_line = True
            if skip_line:
                continue

            for key in affected_list:
                if (key in line) or (key.replace('#', '/') in line):
                    if key not in result_list:
                        result_list[key] = [0, 0, 0]
                        result_list[key][1] = linedate
                    result_list[key][0] += 1
                    result_list[key][2] = linedate
        f.close()

    response_list = {
        '_timeframe': [totalentry[0], totalentry[1], None],
        '_results': result_list
    }
    print(json.dumps(response_list))
