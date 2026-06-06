from flask import jsonify


def response_ok(data):
    return jsonify({"ok": True, "data": data})


def response_fail(message: str, status: int = 400):
    return jsonify({"ok": False, "error": message}), status
