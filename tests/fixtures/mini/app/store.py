"""A tiny CRUD store."""

ITEMS = {}


def create(key, value):
    ITEMS[key] = value
    return value


def read(key):
    return ITEMS.get(key)


def delete(key):
    return ITEMS.pop(key, None)
