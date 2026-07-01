"""
permissions.py — Central catalog of all permissions in SMVS OCR.

Future ma navi facility add karo tyare fakt ahiya ek entry add karo — e automatically
Role Management UI ma dekhaay jashe ane assign kari shakay. No other change needed.

Permission key format: "<group>.<item>"
  admin.dashboard, admin.users, admin.fonts, admin.jobs, admin.cloud,
  admin.feedback, admin.email, admin.roles
  app.ocr (main OCR conversion), app.feedback (submit feedback)
"""

PERMISSION_CATALOG = {
    "Admin Panel Tabs": [
        {"key": "admin.dashboard", "label": "📊 Dashboard"},
        {"key": "admin.users",     "label": "👤 User Management"},
        {"key": "admin.fonts",     "label": "🔤 Uploaded Fonts"},
        {"key": "admin.jobs",      "label": "🗂️ Stored Jobs"},
        {"key": "admin.cloud",     "label": "☁️ Cloud Management"},
        {"key": "admin.feedback",  "label": "💬 Feedback"},
        {"key": "admin.email",     "label": "✉️ Email Settings"},
        {"key": "admin.roles",     "label": "🛡️ Role Management"},
    ],
    "Application Features": [
        {"key": "app.ocr",      "label": "📄 OCR Conversion (main app)"},
        {"key": "app.feedback", "label": "💬 Submit Feedback"},
    ],
}

# Flat list of all valid permission keys
ALL_PERMISSIONS = [item["key"] for group in PERMISSION_CATALOG.values() for item in group]

# superadmin = wildcard, everything
SUPERADMIN_ROLE = "superadmin"


def all_keys():
    return list(ALL_PERMISSIONS)


def catalog():
    return PERMISSION_CATALOG


def has_permission(role_name, permission, role_permissions_lookup):
    """role_permissions_lookup: function(role_name) -> list[str] | None
    superadmin = always True. Otherwise check role's granted permission list."""
    if role_name == SUPERADMIN_ROLE:
        return True
    perms = role_permissions_lookup(role_name)
    if not perms:
        return False
    if "*" in perms:
        return True
    return permission in perms


def admin_tab_permissions():
    """Just the admin.* tab keys — for building the 'grant admin rights' checklist."""
    return [item for item in PERMISSION_CATALOG["Admin Panel Tabs"]]
