from db import session


# for loop with session.execute — should fire db-call-in-loop
def process_items(items):
    for item in items:
        session.execute("INSERT INTO log VALUES (?)", [item])


# non-loop call — must NOT fire
def setup():
    session.execute("CREATE TABLE IF NOT EXISTS log (val TEXT)")
