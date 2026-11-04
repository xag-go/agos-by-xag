"""The Hire service: a hire's kit, its Readiness and its onboarding test, split out of actions/hire_kit.py.

Each module imports only the modules before it in the service's dependency order (no
cycles); the package itself imports nothing, so loading one part stays cheap.

Must not: import its own modules here (loading one part stays cheap) or hold code.
"""

__all__: list[str] = []
