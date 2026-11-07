
import sqlite3

DB_PATH = "cqa.db"

new_columns = {
    "status": "VARCHAR NOT NULL DEFAULT 'completed'",
    "checklist_version": "VARCHAR",
    "result_json": "TEXT",
    "error": "TEXT"
}

connection = sqlite3.connect(DB_PATH)
cursor = connection.cursor()

cursor.execute("PRAGMA table_info(evaluations)")
existing_columns = {
    row[1] for row in cursor.fetchall()
}

for column_name, column_type in new_columns.items():
    if column_name not in existing_columns:
        cursor.execute(
            f"ALTER TABLE evaluations ADD COLUMN "
            f"{column_name} {column_type}"
        )
        print(f"Added column: {column_name}")
    else:
        print(f"Already exists: {column_name}")

connection.commit()

cursor.execute("PRAGMA table_info(evaluations)")
print("\nUpdated evaluations table:")

for column in cursor.fetchall():
    print(column[1], column[2])

connection.close()

print("\nDatabase migration completed!")
