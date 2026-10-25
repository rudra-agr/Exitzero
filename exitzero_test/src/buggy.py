# Bug 1: ZeroDivisionError
def divide(a, b):
    return a / b

# Bug 2: KeyError
def get_user(user_id):
    users = {1: "Guts", 2: "Lectar"}
    return users[user_id]

# Bug 3: ImportError
import pandas as totally_fake_module

# Bug 4: TypeError
def add_numbers(a, b):
    return a + b

print(divide(10, 0))
print(get_user(99))
print(add_numbers("hello", 5))
