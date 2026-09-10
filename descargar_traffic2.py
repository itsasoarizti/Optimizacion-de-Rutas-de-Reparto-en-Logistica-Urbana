"""
DATASET TRÁFICO 2024-2026

Este notebook descarga el dataset "Chicago Traffic Tracker - Historical Congestion Estimates 
by Segment - 2024-2026" desde el portal de datos de Chicago usando la API SODA2.

Troceamos el dataset por mes usando un filtro de fechas ($where sobre la columna
`time`).

Filtramos las filas con speed = -1 (-1 significa que no hay ninguna estimación disponible) 
y seleccionamos solo las columnas necesarias. Guardamos el resultado como varios archivos Parquet 
dentro de una carpeta (`chicago_traffic_data`), organizados por mes. Así podremos reanudar si se interrumpe.
"""

import time
import requests
from pathlib import Path
from datetime import date

import pyarrow as pa
import pyarrow.parquet as pq

# CONFIGURACIÓN

dataset_id = "4g9f-3jbs"
base_url = f"https://data.cityofchicago.org/resource/{dataset_id}.json"

# Columnas que queremos
columnas = [
    "time",
    "segment_id",
    "speed",
    "street",
    "direction",
    "from_street",
    "to_street",
    "length",
    "day_of_week",
    "month",
    "start_latitude",
    "start_longitude",
    "end_latitude",
    "end_longitude",
]

dir_output = Path("chicago_traffic_data")

tam_pag = 25000

TIMEOUT_SEGUNDOS = 300
ESPERA_MAX_SEGUNDOS = 300  # max de espera entre reintentos

# rango de fechas, troceamos por mes
FECHA_INICIO = date(2023, 1, 1)
FECHA_FIN = date(2027, 1, 1)

# tipos de datos por columna
SCHEMA = pa.schema([
    ("time", pa.string()),
    ("segment_id", pa.string()),
    ("speed", pa.float64()),
    ("street", pa.string()),
    ("direction", pa.string()),
    ("from_street", pa.string()),
    ("to_street", pa.string()),
    ("length", pa.float64()),
    ("day_of_week", pa.float64()),
    ("month", pa.float64()),
    ("start_latitude", pa.float64()),
    ("start_longitude", pa.float64()),
    ("end_latitude", pa.float64()),
    ("end_longitude", pa.float64()),
])

columnas_num = {
    "speed", "length", "day_of_week", "month", "start_latitude", "start_longitude",
    "end_latitude", "end_longitude",
}

# UTILIDADES DE MESES

def generar_meses(inicio: date, fin: date):
    """Generamos tuplas (etiqueta, inicio_iso, fin_iso) para cada mes entre
    inicio (incluido) y fin (excluido)."""
    y, m = inicio.year, inicio.month
    while date(y, m, 1) < fin:
        siguiente_m = m + 1 if m < 12 else 1
        siguiente_y = y if m < 12 else y + 1
        etiqueta = f"{y:04d}-{m:02d}"
        ini_iso = f"{y:04d}-{m:02d}-01T00:00:00.000"
        fin_iso = f"{siguiente_y:04d}-{siguiente_m:02d}-01T00:00:00.000"
        yield etiqueta, ini_iso, fin_iso
        y, m = siguiente_y, siguiente_m


# DESCARGA

def build_params(mes_ini_iso: str, mes_fin_iso: str, offset: int) -> dict:
    where = (
        f"speed != -1 "
        f"AND time >= '{mes_ini_iso}' "
        f"AND time < '{mes_fin_iso}'"
    )
    return {
        "$select": ",".join(columnas),
        "$where": where,
        # ordenamos por la misma columna que filtramos (time), con
        # segment_id como desempate para que la paginación sea estable
        "$order": "time, segment_id",
        "$limit": tam_pag,
        "$offset": offset,
    }


def fetch_page(session: requests.Session, etiqueta: str, mes_ini_iso: str, mes_fin_iso: str, offset: int) -> list[dict]:
    """Descarga una página. Si falla, lo reintenta indefinidamente
    (hasta ESPERA_MAX_SEGUNDOS), así que el script no se cae y no hace
    falta lanzarlo otra vez a mano."""
    params = build_params(mes_ini_iso, mes_fin_iso, offset)
    intento = 0

    while True:
        intento += 1
        try:
            response = session.get(base_url, params=params, timeout=TIMEOUT_SEGUNDOS)
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            espera = min(5 * intento, ESPERA_MAX_SEGUNDOS)
            print(f"  [{etiqueta} | offset {offset}] intento {intento} falló ({exc}). "
                  f"Reintentando en {espera}s...")
            time.sleep(espera)


def rows_to_table(rows: list[dict]) -> pa.Table:
    columns_data = {col: [] for col in columnas}

    for row in rows:
        for col in columnas:
            value = row.get(col)
            if value is None or value == "":
                columns_data[col].append(None)
            elif col in columnas_num:
                try:
                    columns_data[col].append(float(value))
                except (TypeError, ValueError):
                    columns_data[col].append(None)
            else:
                columns_data[col].append(str(value))

    arrays = [pa.array(columns_data[col], type=SCHEMA.field(col).type) for col in columnas]
    return pa.Table.from_arrays(arrays, schema=SCHEMA)


def marker_mes_completo(etiqueta: str) -> Path:
    return dir_output / f"_DONE_{etiqueta}"


def find_resume_offset_mes(etiqueta: str) -> int:
    """Offset desde el que continuar dentro de un mes, mirando que páginas
    de ese mes ya existen."""
    existentes = []
    for p in dir_output.glob(f"part_{etiqueta}_*.parquet"):
        try:
            offset_str = p.stem.replace(f"part_{etiqueta}_", "")
            existentes.append(int(offset_str))
        except ValueError:
            continue

    if not existentes:
        return 0

    last_offset = max(existentes)
    last_file = dir_output / f"part_{etiqueta}_{last_offset:012d}.parquet"
    try:
        pq.read_table(last_file)
    except Exception:
        print(f"  {last_file.name} parece incompleto, se vuelve a descargar.")
        last_file.unlink(missing_ok=True)
        return last_offset

    return last_offset + tam_pag


def descargar_mes(session: requests.Session, etiqueta: str, mes_ini_iso: str, mes_fin_iso: str) -> None:
    if marker_mes_completo(etiqueta).exists():
        print(f"Mes {etiqueta}: ya estaba completo, se salta.")
        return

    offset = find_resume_offset_mes(etiqueta)
    if offset > 0:
        print(f"Mes {etiqueta}: reanudando desde offset={offset:,}")

    while True:
        print(f"Mes {etiqueta}: descargando filas {offset:,} - {offset + tam_pag:,} ...")
        rows = fetch_page(session, etiqueta, mes_ini_iso, mes_fin_iso, offset)

        if not rows:
            print(f"Mes {etiqueta}: completo.")
            marker_mes_completo(etiqueta).touch()
            return

        table = rows_to_table(rows)

        part_path = dir_output / f"part_{etiqueta}_{offset:012d}.parquet"
        tmp_path = part_path.with_suffix(".parquet.tmp")
        pq.write_table(table, tmp_path, compression="snappy")
        tmp_path.rename(part_path)

        offset += tam_pag
        time.sleep(0.3 if api_traffic else 1.0)

def main() -> None:
    session = requests.Session()
    headers = {"Accept": "application/json"}
    if api_traffic:
        headers["X-App-Token"] = api_traffic
    session.headers.update(headers)

    dir_output.mkdir(exist_ok=True)

    for etiqueta, mes_ini_iso, mes_fin_iso in generar_meses(FECHA_INICIO, FECHA_FIN):
        descargar_mes(session, etiqueta, mes_ini_iso, mes_fin_iso)

    print("\nDescarga completa de todos los meses.")
    print(f"Archivos guardados en: {dir_output.resolve()}")
    print(f"Para leer todo junto: pd.read_parquet('{dir_output}/')")


if __name__ == "__main__":
    main()
