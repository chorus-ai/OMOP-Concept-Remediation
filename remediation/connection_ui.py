"""An opt-in prompt in a live Jupyter kernel; no network call at import."""
def ask_to_connect():
    try:
        from IPython import get_ipython
    except ImportError:
        return False
    if getattr(get_ipython(), "kernel", None) is None:
        return False
    return input("Type CONNECT to connect to the approved database (blank cancels): ").strip() == "CONNECT"
