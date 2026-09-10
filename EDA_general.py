"""
En este notebook creamos las funciones generales que usaremos
para los EDA de nuestros conjunto de datos.
"""


import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

import folium
from folium.plugins import HeatMap


def resumen_general(df):
    """Este código da una visión general de cualquier dataframe: dimensiones, tipos
    y las primeras filas."""

    print(f"Dimensiones: {df.shape[0]:,} filas x {df.shape[1]} columnas")
    print("\nTipos de dato por columna:")
    print(df.dtypes)
    print("\nPrimeras filas:")
    print(df.head())


def calidad_datos(df, id_col=None):
    """Comprobamos los nulos por columna y duplicados."""
    
    nulls = df.isnull().sum().sort_values(ascending=False)
    null_pct = (nulls / len(df) * 100).round(2)
    calidad = pd.DataFrame({"nulos": nulls, "% nulos": null_pct})
    print("Valores nulos por columna:")
    print(calidad[calidad["nulos"] > 0])

    high_null_cols = null_pct[null_pct > 80].index.tolist()
    if high_null_cols:
        print(f"\nColumnas con >80% de nulos (candidatas a eliminar): {high_null_cols}")

    if id_col is not None:
        dup_count = df.duplicated(subset=[id_col]).sum()
        print(f"\nRegistros duplicados según '{id_col}': {dup_count:,}")


def analisis_temporal(df, date_col, day_col=None, hour_col=None, date_format=None, evento=None):
    """Esta función parsea la columna de fecha, muestra el rango y crea 4 gráficos:
    accidentes por año, mes, día de la semana y hora.
    """

    fechas = pd.to_datetime(df[date_col], format=date_format, errors="coerce")

    n_invalid = fechas.isna().sum()
    print(f"Fechas que no se pudieron parsear: {n_invalid:,}")
    print(f"Rango de fechas: {fechas.min()} -> {fechas.max()}")

    year = fechas.dt.year
    month = fechas.dt.month
    hour = df[hour_col] if hour_col else fechas.dt.hour
    day = df[day_col] if day_col else fechas.dt.dayofweek

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))

    year.value_counts().sort_index().plot(kind="bar", ax=axes[0, 0])
    axes[0, 0].set_title(f"{evento} por año")

    month.value_counts().sort_index().plot(kind="bar", ax=axes[0, 1])
    axes[0, 1].set_title(f"{evento} por mes (estacionalidad)")

    day.value_counts().sort_index().plot(kind="bar", ax=axes[1, 0])
    axes[1, 0].set_title(f"{evento} por día de la semana")

    hour.value_counts().sort_index().plot(kind="bar", ax=axes[1, 1])
    axes[1, 1].set_title(f"{evento} por hora del día")
    axes[1, 1].set_xlabel("Hora")

    plt.tight_layout()
    plt.show()

    return fechas

def analisis_geografico(df, lat_col, lon_col, mostrar_heatmap=True):
    """Esta función comprueba coordenadas nulas y pinta un heatmap con
    folium."""

    n_sin_coords = df[[lat_col, lon_col]].isnull().any(axis=1).sum()
    print(f"Filas sin coordenadas: {n_sin_coords:,} "
          f"({n_sin_coords / len(df) * 100:.1f}%)")

    centro = [df[lat_col].mean(), df[lon_col].mean()]
    m = folium.Map(location=centro, zoom_start=11)

    heat_data = df[[lat_col, lon_col]].dropna().values.tolist()
    HeatMap(heat_data, radius=8, blur=12, max_zoom=13).add_to(m)

    return m

def analisis_calles(df, street_col, dir_col=None):
    """Esta función nos da el top 15 de calles con más incidencias y
    distribución de dirección.
    """
    print(f"Top 15 '{street_col}' con más registros:")
    print(df[street_col].value_counts().head(15))

    if dir_col:
        print(f"\nDistribución de {dir_col}:")
        print(df[dir_col].value_counts(dropna=False))