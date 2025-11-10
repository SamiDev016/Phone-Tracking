import frappe
from frappe import _

@frappe.whitelist()
def receive_call_log(data=None):
    try:
        if frappe.request and frappe.request.get_data():
            import json
            try:
                payload = json.loads(frappe.request.get_data().decode("utf-8"))
            except Exception as e:
                payload = frappe.local.form_dict.get('data') and frappe.parse_json(frappe.local.form_dict.get('data')) or {}
        else:
            payload = frappe.parse_json(data) if data else frappe.local.form_dict
        
        call_doc = frappe.get_doc({
            "doctype": "Call Logs",
            "device_id": payload.get("device_id"),
            "caller_number": payload.get("caller_number"),
            "receiver_number": payload.get("receiver_number"),
            "call_type": payload.get("call_type"),
            "duration": payload.get("duration"),
            "timestamp": payload.get("timestamp"),
            "call_id": payload.get("call_id"),
        })

        call_doc.insert(ignore_permissions=True)
        frappe.db.commit()
        return {
            "status": "success",
            "message": "Call log received successfully",
        }
    except Exception as e:
        frappe.log_error(f"Error receiving call log: {str(e)}")
        return {
            "status": "error",
            "message": "Failed to receive call log",
        }
            