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
parser.add_argument("-d", "--db-path", help="Path to SQLite DB", required=False, default="/home/awx/known_issues.sqlite")
args = parser.parse_args()

import sqlite3
import os

login = args.user
password = args.password
db_path = args.db_path

if not login or not password:
    print("Error: Username and Password are required. Provide via arguments.")
    sys.exit(1)

# Determine YouTrack Base URL
if args.env == "staging":
    youtrack_base_url = "https://yt-staging.int.portaone.com"
else:
    youtrack_base_url = "https://youtrack.portaone.com"

def format_val(v):
    if v is None:
        return 'N/A'
    if isinstance(v, list):
        res = ', '.join([str(x.get('name', x)) if isinstance(x, dict) else str(x) for x in v if x])
        return res if res else 'N/A'
    elif isinstance(v, dict):
        res = v.get('name', '')
        return str(res) if res else 'N/A'
    elif v:
        return str(v)
    return 'N/A'

def get_db_issue_details(issue_id, db_path):
    """
    Retrieve issue details from local SQLite database.
    Table structure: Single table, Known_Issues
    i_known_issue: internal ID
    issue: dev task (e.g. SIP-12345)
    name: subject of the dev task
    committed_to: list of releases where the fix was committed to
    summary: summary of the task
    """
    if not os.path.isfile(db_path):
        # sys.stderr.write(f"DEBUG: DB file not found at {db_path}\n")
        return None

    try:
        conn = sqlite3.connect(db_path)
        # Allow accessing columns by name
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Query by 'issue' column matching the issue_id (e.g. SIP-12345)
        cursor.execute("SELECT summary, committed_to, name FROM Known_Issues WHERE issue = ?", (issue_id,))
        row = cursor.fetchone()
        conn.close()

        if row:
            return {
                'summary': row['summary'],
                'committed_to': row['committed_to'],
                'name': row['name']
            }
        return None
    except sqlite3.Error as e:
        sys.stderr.write(f"Error reading DB: {e}\n")
        return None

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
            
        response = requests.get(url, **request_kwargs, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            for field in data.get('customFields', []):
                name = field.get('name')
                val = field.get('value')

                if name == 'Committed To':
                    details['committed_to'] = format_val(val)

                if name == 'State' or name == 'Status':
                    res = format_val(val)
                    if res != 'N/A' or details['task_status'] == 'N/A':
                        details['task_status'] = res
        else:
            sys.stderr.write(f"Warning: Failed to fetch {issue_id}. Status: {response.status_code}\n")
        return details
    except Exception as e:
        sys.stderr.write(f"Error fetching {issue_id}: {str(e)}\n")
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

                # Extract issues safely (permissive match for 'major')
                processed_issues = []
                sys.stderr.write(f"DEBUG: Starting issue extraction from {len(json_data)} items.\n")
                for item in json_data:
                    if not isinstance(item, dict):
                        continue
                    
                    raw_severity = str(item.get("severity", "")).strip().lower()
                    if "major" in raw_severity:
                        issue_id = item.get("id")
                        subject = item.get("subject")
                        processed_issues.append({
                            "id": str(issue_id) if issue_id else "N/A",
                            "subject": str(subject).lstrip() if subject else "N/A"
                        })
                    else:
                        sys.stderr.write(f"DEBUG: Skipping non-major issue: ID={item.get('id')}, Severity='{item.get('severity')}'\n")
                
                sys.stderr.write(f"DEBUG: Found {len(processed_issues)} total issues to process.\n")

                # Print the table header
                print("||#||Known issue||Summary||Committed To||Task Status||Status||Comment||Time spent, min||")

                # Print the extracted elements
                for i, issue in enumerate(processed_issues, start=1):
                    try:
                        issue_id = issue.get('id', 'N/A')
                        issue_subject = issue.get('subject', 'N/A')
                        sys.stderr.write(f"DEBUG: Processing row {i}: ID={issue_id}\n")
                        
                        issue_link = f"{youtrack_base_url}/issue/{issue_id}" if issue_id != 'N/A' else '#'
                        
                        # 1. Get YT Details first (default source)
                        details = get_issue_details(issue_id, (login, password), args.token) if issue_id != 'N/A' else {'committed_to': 'N/A', 'task_status': 'N/A'}

                        # 2. Get DB Details (for Summary column ONLY)
                        db_summary = ' '
                        if issue_id != 'N/A':
                            db_details = get_db_issue_details(issue_id, db_path)
                            if db_details:
                                if db_details.get('summary'):
                                    db_summary = db_details['summary']
                        
                        # f-strings used for cleaner formatting
                        print(f"|{i}|[{issue_subject}|{issue_link}]|{db_summary}|{details['committed_to']}|{details['task_status']}|{{status:title=Pending|colour=grey}}| | |")
                    except Exception as e:
                        sys.stderr.write(f"CRITICAL Error processing row {i} (ID: {issue.get('id')}): {str(e)}\n")
                        # Print a fallback row to keep the table structure intact
                        print(f"|{i}|[Error processing issue {issue.get('id')}|#]|N/A|N/A|{{status:title=Error|colour=red}}| | |")
            
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
