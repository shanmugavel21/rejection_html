from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pathlib import Path
from pydantic import BaseModel
import os
import psycopg
from dotenv import load_dotenv

load_dotenv()

app = FastAPI()

BASE_DIR = Path(__file__).resolve().parent


def get_connection():
    return psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT"),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        sslmode="require",
    )


FAULTS = [
    ("Conveyor", "Frame Coating Fault - MS"),
    ("Conveyor", "Leg / patti spot broken"),
    ("Conveyor", "Frame Dent"),
    ("Conveyor", "Rubber Leg Fault"),
    ("Conveyor", "Dial Plate Sticker Damage"),
    ("Conveyor", "Dial Plate Scratches / printing issues"),
    ("Conveyor", "Knob Scratches / printing issues"),
    ("Conveyor", "Glass Broken"),
    ("Conveyor", "Glass Acid mark / Printing issue"),
    ("Conveyor", "O Ring Fault"),
    ("Conveyor", "Fixed Tray - Small"),
    ("Conveyor", "Fixed Tray - Big"),
    ("Conveyor", "Fixed Tray - Jumbo"),
    ("Conveyor", "Bundy Tube Damage"),
    ("Conveyor", "Bundy Tube Leak"),
    ("Process", "Mixing Tube Fault - Small"),
    ("Process", "Mixing Tube Fault - Big"),
    ("Process", "Mixing Tube Fault - Jumbo"),
    ("Process", "Mixing Tube Broken"),
    ("Process", "Sim OFF"),
    ("Process", "Sim HIGH"),
    ("Process", "Function Tight"),
    ("Process", "Flame LOW"),
    ("Process", "Flame HIGH"),
    ("Process", "Jet Block"),
    ("Process", "Pipe Block"),
    ("Process", "Burner Fault (W/O Pin)"),
    ("Process", "Burner Fault (I/O Flame)"),
    ("Process", "Burner Coating Fault"),
    ("Process", "Panstand Rejection - Seating / Bend"),
    ("Process", "Panstand Rejection - Coating fault"),
    ("Process", "Panstand Rejection - Pin removed"),
    ("Process", "PC Box Damage"),
    ("Process", "PC Box Vendor Rejection"),
    ("Process", "Dry Air Leak Testing"),
]


FAULT_TO_SECTION = {
    fault_name: section
    for section, fault_name in FAULTS
}


def create_production_table():
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS production_register (
                    id SERIAL PRIMARY KEY,
                    report_date DATE NOT NULL,
                    shift VARCHAR(50) NOT NULL,
                    model_name VARCHAR(200) NOT NULL,
                    production_count INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(report_date, shift, model_name)
                )
            """)

        conn.commit()

    finally:
        conn.close()


@app.on_event("startup")
def startup_event():
    create_production_table()


class RejectionItem(BaseModel):
    fault_name: str
    supplier: int = 0
    process: int = 0


class ProductionItem(BaseModel):
    model_name: str
    production_count: int = 0


class RejectionData(BaseModel):
    report_date: str
    shift: str
    data: list[RejectionItem] = []
    production: list[ProductionItem] = []


@app.get("/", response_class=HTMLResponse)
def home():
    html_path = BASE_DIR / "templates" / "index.html"
    return html_path.read_text(encoding="utf-8")


@app.get("/rejections")
def get_rejections(report_date: str, shift: str):
    conn = get_connection()

    try:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    fault_name,
                    supplier_rejection,
                    process_rejection
                FROM rejection_register
                WHERE report_date = %s
                  AND shift = %s
            """, (report_date, shift))

            rows = cur.fetchall()

            saved_data = {
                row[0]: {
                    "supplier": row[1] or 0,
                    "process": row[2] or 0
                }
                for row in rows
            }

            result = []

            for section, fault_name in FAULTS:

                values = saved_data.get(
                    fault_name,
                    {
                        "supplier": 0,
                        "process": 0
                    }
                )

                result.append({
                    "fault_name": fault_name,
                    "supplier": values["supplier"],
                    "process": values["process"]
                })

            return {
                "success": True,
                "data": result
            }

    finally:
        conn.close()


@app.get("/production")
def get_production(report_date: str, shift: str):
    conn = get_connection()

    try:
        with conn.cursor() as cur:

            cur.execute("""
                SELECT
                    model_name,
                    production_count
                FROM production_register
                WHERE report_date = %s
                  AND shift = %s
                ORDER BY id
            """, (report_date, shift))

            rows = cur.fetchall()

            result = [
                {
                    "model_name": row[0],
                    "production_count": row[1] or 0
                }
                for row in rows
            ]

            return {
                "success": True,
                "data": result
            }

    finally:
        conn.close()


@app.post("/save")
def save_data(payload: RejectionData):
    conn = get_connection()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                DELETE FROM rejection_register
                WHERE report_date = %s
                  AND shift = %s
            """, (
                payload.report_date,
                payload.shift
            ))

            for item in payload.data:

                supplier = item.supplier or 0
                process = item.process or 0

                if supplier == 0 and process == 0:
                    continue

                section = FAULT_TO_SECTION.get(
                    item.fault_name,
                    "Process"
                )

                cur.execute("""
                    INSERT INTO rejection_register
                    (
                        report_date,
                        shift,
                        section,
                        fault_name,
                        supplier_rejection,
                        process_rejection
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    payload.report_date,
                    payload.shift,
                    section,
                    item.fault_name,
                    supplier,
                    process
                ))

            cur.execute("""
                DELETE FROM production_register
                WHERE report_date = %s
                  AND shift = %s
            """, (
                payload.report_date,
                payload.shift
            ))

            for item in payload.production:

                count = item.production_count or 0

                if count <= 0:
                    continue

                if not item.model_name.strip():
                    continue

                cur.execute("""
                    INSERT INTO production_register
                    (
                        report_date,
                        shift,
                        model_name,
                        production_count
                    )
                    VALUES (%s, %s, %s, %s)
                """, (
                    payload.report_date,
                    payload.shift,
                    item.model_name.strip(),
                    count
                ))

        conn.commit()

        return {
            "success": True,
            "message": "Data saved successfully"
        }

    except Exception as e:

        conn.rollback()

        return {
            "success": False,
            "message": str(e)
        }

    finally:
        conn.close()


@app.get("/daily-total")
def daily_total(report_date: str):

    conn = get_connection()

    try:

        with conn.cursor() as cur:

            # Overall rejection
            cur.execute("""
                SELECT
                    COALESCE(SUM(supplier_rejection), 0),
                    COALESCE(SUM(process_rejection), 0)
                FROM rejection_register
                WHERE report_date = %s
            """, (report_date,))

            rejection_row = cur.fetchone()

            supplier_total = rejection_row[0] or 0
            process_total = rejection_row[1] or 0
            rejection_total = supplier_total + process_total


            # Overall production
            cur.execute("""
                SELECT
                    COALESCE(SUM(production_count), 0)
                FROM production_register
                WHERE report_date = %s
            """, (report_date,))

            production_row = cur.fetchone()

            production_total = production_row[0] or 0


            # All fault rows, including zero values
            rejection_by_fault = []

            for section, fault_name in FAULTS:

                cur.execute("""
                    SELECT
                        COALESCE(SUM(supplier_rejection), 0),
                        COALESCE(SUM(process_rejection), 0)
                    FROM rejection_register
                    WHERE report_date = %s
                      AND fault_name = %s
                """, (
                    report_date,
                    fault_name
                ))

                row = cur.fetchone()

                supplier = row[0] or 0
                process = row[1] or 0

                rejection_by_fault.append({
                    "fault_name": fault_name,
                    "supplier": supplier,
                    "process": process,
                    "total": supplier + process
                })


            # Shift-wise production
            cur.execute("""
                SELECT
                    shift,
                    COALESCE(SUM(production_count), 0)
                FROM production_register
                WHERE report_date = %s
                GROUP BY shift
            """, (report_date,))

            shift_rows = cur.fetchall()

            shift_order = {
                "1st Shift": 1,
                "General Shift": 2,
                "2nd Shift": 3
            }

            production_by_shift = [
                {
                    "shift": row[0],
                    "production": row[1] or 0
                }
                for row in shift_rows
            ]

            production_by_shift.sort(
                key=lambda x: shift_order.get(
                    x["shift"],
                    99
                )
            )


            # Model-wise production
            cur.execute("""
                SELECT
                    model_name,
                    COALESCE(SUM(production_count), 0)
                FROM production_register
                WHERE report_date = %s
                GROUP BY model_name
                ORDER BY model_name
            """, (report_date,))

            model_rows = cur.fetchall()

            production_by_model = [
                {
                    "model_name": row[0],
                    "production": row[1] or 0
                }
                for row in model_rows
            ]


            return {
                "success": True,
                "report_date": report_date,
                "production_total": production_total,
                "supplier_total": supplier_total,
                "process_total": process_total,
                "rejection_total": rejection_total,
                "rejection_by_fault": rejection_by_fault,
                "production_by_shift": production_by_shift,
                "production_by_model": production_by_model
            }

    finally:
        conn.close()


@app.delete("/delete")
def delete_data(report_date: str, shift: str):

    conn = get_connection()

    try:

        with conn.cursor() as cur:

            cur.execute("""
                DELETE FROM rejection_register
                WHERE report_date = %s
                  AND shift = %s
            """, (
                report_date,
                shift
            ))

            cur.execute("""
                DELETE FROM production_register
                WHERE report_date = %s
                  AND shift = %s
            """, (
                report_date,
                shift
            ))

        conn.commit()

        return {
            "success": True,
            "message": "Data deleted successfully"
        }

    except Exception as e:

        conn.rollback()

        return {
            "success": False,
            "message": str(e)
        }

    finally:
        conn.close()
