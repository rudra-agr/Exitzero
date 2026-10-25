def process(data):
    return data["name"].upper()

# Bug: passing wrong type
process(["Guts", "Lectar"])