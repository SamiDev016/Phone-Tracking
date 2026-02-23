import frappe
import json
from datetime import datetime, timedelta
import requests

@frappe.whitelist()
def receive_call_log(data=None):
    try:
        if frappe.request and frappe.request.get_data():
            try:
                payload = json.loads(frappe.request.get_data().decode("utf-8"))
            except Exception:
                payload = (
                    frappe.local.form_dict.get("data")
                    and frappe.parse_json(frappe.local.form_dict.get("data"))
                    or {}
                )
        else:
            payload = frappe.parse_json(data) if data else frappe.local.form_dict

        call_status = payload.get("call_status")
        if call_status == "Missed":
            call_status = "No Answer"

        api_user = frappe.session.user
        links = []
        if payload.get("call_type") == "Outgoing":
            caller = api_user
            received_by = ""
            phone_to_check = payload.get("receiver_number")
            r_contact = get_contact_by_phone(phone_to_check)
            custom_receiver_contact = r_contact
        elif payload.get("call_type") == "Incoming":
            caller = ""
            received_by = api_user
            phone_to_check = payload.get("caller_number")
            r_contact = get_contact_by_phone(phone_to_check)
            custom_receiver_contact = r_contact

        normalized_number = normalize_phone(phone_to_check)
        matches = find_phone_owner(normalized_number)

        seen = set()
        for m in matches:
            key = (m["doctype"], m["name"])
            if key in seen:
                continue
            seen.add(key)
            links.append({
                "link_doctype": m["doctype"],
                "link_name": m["name"],
            })

        duration = payload.get("duration") or 0
        try:
            duration = int(duration)
        except:
            duration = 0

        if payload.get("call_type") == "Incoming" and call_status == "No Answer":
            duration = 0

        timestamp = payload.get("timestamp")
        if timestamp:
            try:
                timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except:
                timestamp = datetime.now()
        else:
            timestamp = datetime.now()

        call_doc = frappe.get_doc({
            "doctype": "Call Logs",
            "device_id": payload.get("device_id"),
            "caller_number": payload.get("caller_number"),
            "receiver_number": payload.get("receiver_number"),
            "call_type": payload.get("call_type"),
            "duration": duration,
            "timestamp": timestamp,
            "call_status": call_status,
            "call_id": payload.get("call_id"),
            "full_name": payload.get("full_name"),
        })

        tp_call_log_doc = frappe.get_doc({
            "doctype": "TP Call Log",
            "id": payload.get("call_id"),
            "to": payload.get("receiver_number"),
            "from": payload.get("caller_number"),
            "type": payload.get("call_type"),
            "status": call_status,
            "duration": duration,
            "caller": caller,
            "receiver": received_by,
            "start_time": timestamp,
            "custom_receiver_contact": custom_receiver_contact,
            "end_time": timestamp + timedelta(seconds=duration),
        })
        settings = frappe.get_doc("TP Call log Settings")
        airtable_base_id = settings.base_id
        airtable_table_name = settings.table_name
        airtable_token = settings.token
        airtable_data ={
            "Call ID": payload.get("call_id"),
            "From": payload.get("caller_number"),
            "To": payload.get("receiver_number"),
            "Type": payload.get("call_type"),
            "Status": call_status,
            "Duration": duration,
            "Start Time": timestamp.isoformat(),
            "End Time": (timestamp + timedelta(seconds=duration)).isoformat(),
            "Device ID": payload.get("device_id"),
            "Full Name": payload.get("full_name"),
        }
        send_to_airtable(airtable_base_id, airtable_table_name, airtable_token, airtable_data)

        for link in links:
            tp_call_log_doc.append("links", link)

        call_doc.insert(ignore_permissions=True)
        tp_call_log_doc.insert(ignore_permissions=True)
        frappe.db.commit()

        return {
            "status": "success",
            "message": "Call log received successfully",
        }

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), "Receive Call Log Error")
        return {
            "status": "error",
            "message": str(e),
        }


def normalize_phone(phone):
    if not phone:
        return None

    phone = phone.strip().replace(" ", "").replace("-", "")

    if phone.startswith("+213"):
        phone = phone[4:]
    elif phone.startswith("00213"):
        phone = phone[5:]

    if phone.startswith("0"):
        phone = phone[1:]

    return phone


def find_phone_owner(phone):
    results = []

    phone = normalize_phone(phone)
    if not phone:
        return results

    targets = [
        ("Customer", ["mobile_no", "phone", "custom_phone_number", "custom_phone_number_2", "custom_phone_number_3"]),
        ("Lead", ["mobile_no", "phone"]),
        ("Contact", ["mobile_no", "phone"]),
        ("Supplier", ["mobile_no", "phone"]),
        ("Employee", ["cell_number"]),
    ]

    for doctype, fields in targets:
        table = f"`tab{doctype}`"

        for field in fields:
            if not frappe.db.has_column(doctype, field):
                continue

            rows = frappe.db.sql(
                f"""
                SELECT name
                FROM {table}
                WHERE REPLACE(REPLACE(REPLACE({field}, ' ', ''), '-', ''), '+', '')
                LIKE %s
                """,
                (f"%{phone}%",),
                as_dict=True
            )

            for row in rows:
                results.append({
                    "doctype": doctype,
                    "name": row.name,
                })

    rows = frappe.db.sql(
        """
        SELECT parent AS name
        FROM `tabContact Phone`
        WHERE REPLACE(REPLACE(REPLACE(phone, ' ', ''), '-', ''), '+', '')
        LIKE %s
        """,
        (f"%{phone}%",),
        as_dict=True
    )

    for row in rows:
        results.append({
            "doctype": "Contact",
            "name": row.name,
        })

    seen = set()
    clean = []
    for r in results:
        key = (r["doctype"], r["name"])
        if key not in seen:
            seen.add(key)
            clean.append(r)

    return clean

def get_contact_by_phone(phone):
    phone = normalize_phone(phone)
    if not phone:
        return None

    if frappe.db.has_column("Contact", "phone"):
        row = frappe.db.sql(
            """
            SELECT name
            FROM `tabContact`
            WHERE REPLACE(REPLACE(REPLACE(phone, ' ', ''), '-', ''), '+', '')
            LIKE %s
            LIMIT 1
            """,
            (f"%{phone}%",),
            as_dict=True
        )

        if row:
            return row[0].name

    row = frappe.db.sql(
        """
        SELECT parent AS name
        FROM `tabContact Phone`
        WHERE REPLACE(REPLACE(REPLACE(phone, ' ', ''), '-', ''), '+', '')
        LIKE %s
        LIMIT 1
        """,
        (f"%{phone}%",),
        as_dict=True
    )

    if row:
        return row[0].name

    return None




def send_to_airtable(airtable_base_id, airtable_table_name, airtable_token, data):
    url = f"https://api.airtable.com/v0/{airtable_base_id}/{airtable_table_name}"
    
    headers = {
        "Authorization": f"Bearer {airtable_token}",
        "Content-Type": "application/json"
    }

    payload = {
        "records": [
            {
                "fields": data
            }
        ]
    }

    response = requests.post(url, json=payload, headers=headers)

    if response.status_code not in (200, 201):
        frappe.log_error(response.text, "Airtable Error")

    return response.json()
