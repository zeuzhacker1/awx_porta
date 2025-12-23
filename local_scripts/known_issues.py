#!/usr/bin/env python3

import argparse
import requests
import json
import getpass
import sys

# Parse command-line arguments
parser = argparse.ArgumentParser(description="Script for simple parsing of known issues before the update")
parser.add_argument("-m", "--mr", help="MR number", required=True)
parser.add_argument("-u", "--user", help="LDAP Username", required=False)
parser.add_argument("-p", "--password", help="LDAP Password", required=False)
parser.add_argument("-t", "--token", help="YouTrack Token", required=False)
parser.add_argument("-e", "--env", help="Environment (prod/staging)", required=False, default="prod")
args = parser.parse_args()

import os

login = args.user
password = args.password

if not login or not password:
    print("Error: Username and Password are required. Provide via arguments.")
    sys.exit(1)

# Determine YouTrack Base URL
if args.env == "staging":
    youtrack_base_url = "https://yt-staging.int.portaone.com"
else:
    youtrack_base_url = "https://youtrack.portaone.com"

def format_val(v):
    if isinstance(v, list):
        res = ', '.join([x.get('name', '') for x in v if x])
        return res if res else 'N/A'
    elif isinstance(v, dict):
        res = v.get('name', '')
        return res if res else 'N/A'
    elif v:
        return str(v)
    return 'N/A'

def get_issue_details(issue_id, auth, token=None):
    details = {'committed_to': 'N/A', 'task_status': 'N/A'}
    try:
        # Use YouTrack REST API to get custom fields
        url = f"{youtrack_base_url}/api/issues/{issue_id}"
        params = {'fields': 'customFields(name,value(name))'}
        
        request_kwargs = {'params': params}
        if token:
            request_kwargs['headers'] = {'Authorization': f'Bearer {token}'}
        else:
            request_kwargs['auth'] = auth
            
        response = requests.get(url, **request_kwargs, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            for field in data.get('customFields', []):
                val = field.get('value')

                if field.get('name') == 'Committed To':
                    details['committed_to'] = format_val(val)
                elif field.get('name') == 'State':
                    details['task_status'] = format_val(val)
                    
        return details
    except Exception as e:
        return details

# Construct the URL with MR number using f-string
url = f"https://portaone.com/resources/protected/release_notes/json/MR{args.mr}.js"

try:
    # Send GET request with basic authentication
    response = requests.get(url, auth=(login, password))

    # Check if the request was successful (status code 200)
    if response.status_code == 200:
        response_body = response.text

        # Define the prefix and suffix to remove
        prefix = "function known_issues() { return "
        suffix = "; }"

        # Check if the response body starts with the prefix and ends with the suffix
        if response_body.startswith(prefix) and response_body.strip().endswith(suffix):
            # Remove the prefix and suffix
            # Note: strip() is used on the end to handle potential trailing newlines
            cleaned_body = response_body[len(prefix):].strip()[:-len(suffix)]
            
            try:
                json_data = json.loads(cleaned_body)

                # Extract major issues with id and subject
                major_issues = [
                    {"id": item["id"], "subject": item["subject"].lstrip()}
                    for item in json_data
                    if item.get("severity") == "Major"
                ]

                # Print the table header
                print("||#||Known issue||Committed To||Task Status||Status||Comment||Time spent, min||")

                # Print the extracted elements
                for i, issue in enumerate(major_issues, start=1):
                    issue_link = f"{youtrack_base_url}/issue/{issue['id']}"
                    details = get_issue_details(issue['id'], (login, password), args.token)
                    # f-strings used for cleaner formatting
                    print(f"|{i}|[{issue['subject']}|{issue_link}]|{details['committed_to']}|{details['task_status']}|{{status:title=Pending|colour=grey}}| | |")
            
            except json.JSONDecodeError as e:
                print(f"Error parsing JSON data: {e}")
        else:
            print("Response body format doesn't match expected pattern (Prefix/Suffix missing).")
            # Debugging aid: print the first 50 chars to see what we actually got
            print(f"Received start of body: {response_body[:50]}")
    else:
        print(f"Failed to retrieve data. Status code: {response.status_code}")
        if response.status_code == 401:
            print("Authentication failed. Check login/password.")

except requests.exceptions.RequestException as e:
    print(f"Network error occurred: {e}")
