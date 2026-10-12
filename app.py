
from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    redirect,
    url_for,
    session
)

import os
import secrets
from decimal import Decimal, InvalidOperation
from datetime import date, timedelta
from functools import wraps

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv
from werkzeug.security import (
    check_password_hash,
    generate_password_hash
)


# ==========================================
# CONFIGURACIÓN GENERAL
# ==========================================

load_dotenv()

app = Flask(__name__)

app.secret_key = os.getenv("SECRET_KEY")

if not app.secret_key:
    raise RuntimeError(
        "Configura SECRET_KEY en tu archivo .env"
    )

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.getenv(
        "SESSION_COOKIE_SECURE", "false"
    ).lower() == "true"
)


# ==========================================
# CONEXIÓN A SUPABASE
# ==========================================

def conectar_bd():
    return psycopg2.connect(
        host=os.getenv("DB_HOST"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        dbname=os.getenv("DB_NAME", "postgres"),
        port=os.getenv("DB_PORT", "5432"),
        connect_timeout=10,
        sslmode="require"
    )


# ==========================================
# PROTECCIÓN DE RUTAS
# ==========================================

def login_requerido(funcion):

    @wraps(funcion)
    def decorador(*args, **kwargs):

        if not session.get("admin_autenticado"):
            return redirect(url_for("login"))

        if not session.get("id_usuario"):
            session.clear()
            return redirect(url_for("login"))

        return funcion(*args, **kwargs)

    return decorador


# ==========================================
# PÁGINA PRINCIPAL
# ==========================================

@app.route("/")
def inicio():

    if session.get("admin_autenticado"):
        return redirect(url_for("panel"))

    return redirect(url_for("login"))


# ==========================================
# LOGIN
# ==========================================

@app.route("/login")
def login():

    if session.get("admin_autenticado"):
        return redirect(url_for("panel"))

    return render_template("login.html")


# ==========================================
# VALIDAR LOGIN
# ==========================================

@app.route("/validar_login", methods=["POST"])
def validar_login():

    usuario = request.form.get("usuario", "").strip()
    contrasena = request.form.get("contrasena", "")

    if not usuario or not contrasena:
        return "Ingresa usuario y contraseña.", 400

    try:
        with conectar_bd() as conexion:
            with conexion.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                cursor.execute("""
                    SELECT id, nombre_usuario, contrasena
                    FROM public.usuario
                    WHERE LOWER(nombre_usuario) = LOWER(%s)
                """, (usuario,))

                datos = cursor.fetchone()

        acceso_valido = False

        if datos:

            almacenada = datos["contrasena"]

            if almacenada.startswith(("scrypt:", "pbkdf2:")):
                acceso_valido = check_password_hash(
                    almacenada,
                    contrasena
                )
            else:
                acceso_valido = almacenada == contrasena

        if acceso_valido:

            session.clear()

            session["id_usuario"] = datos["id"]
            session["usuario"] = datos["nombre_usuario"]
            session["admin_autenticado"] = True

            return redirect(url_for("panel"))

        return "Usuario o contraseña incorrectos.", 401

    except psycopg2.Error as e:
        print("Error en login:", e)
        return "Error al conectar con la base de datos.", 500



# ==========================================
# PANEL PRINCIPAL CON 3 SEGMENTADORES
# ==========================================

@app.route("/panel")
@login_requerido
def panel():

    id_admin = session["id_usuario"]
    hoy = date.today()
    limite_proximo = hoy + timedelta(days=7)

    # --------------------------------------
    # FILTROS RECIBIDOS DESDE EL DASHBOARD
    # --------------------------------------

    anio_solicitado = request.args.get("periodo", "todos").strip()
    categoria_solicitada = request.args.get("categoria", "todas").strip()
    contacto_solicitado = request.args.get("contacto", "todos").strip()

    if contacto_solicitado not in (
        "todos", "completo", "parcial", "sin"
    ):
        contacto_solicitado = "todos"

    try:
        with conectar_bd() as conexion:
            with conexion.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                # --------------------------------------
                # OPCIONES REALES PARA LOS SEGMENTADORES
                # --------------------------------------

                cursor.execute("""
                    SELECT c.id, c.nombre
                    FROM public.categorias c
                    ORDER BY c.nombre ASC
                """)

                categorias_disponibles = cursor.fetchall()

                ids_categorias = {
                    str(c["id"]) for c in categorias_disponibles
                }

                if categoria_solicitada not in ids_categorias:
                    categoria_solicitada = "todas"

                cursor.execute("""
                    SELECT DISTINCT anio
                    FROM (
                        SELECT
                            EXTRACT(YEAR FROM p.fecha_registro)::int
                            AS anio
                        FROM public.proveedor p
                        WHERE p.id_usuario = %s
                          AND p.fecha_registro IS NOT NULL

                        UNION

                        SELECT
                            EXTRACT(YEAR FROM r.fecha_pago)::int
                            AS anio
                        FROM public.recordatorios_pago r
                        INNER JOIN public.proveedor p
                            ON p.id = r.id_proveedor
                        WHERE p.id_usuario = %s
                          AND r.fecha_pago IS NOT NULL
                    ) AS periodos
                    WHERE anio IS NOT NULL
                    ORDER BY anio DESC
                """, (id_admin, id_admin))

                anios_disponibles = [
                    int(fila["anio"])
                    for fila in cursor.fetchall()
                ]

                if hoy.year not in anios_disponibles:
                    anios_disponibles.insert(0, hoy.year)

                anios_disponibles = sorted(
                    set(anios_disponibles),
                    reverse=True
                )

                if (
                    anio_solicitado != "todos"
                    and (
                        not anio_solicitado.isdigit()
                        or int(anio_solicitado)
                        not in anios_disponibles
                    )
                ):
                    anio_solicitado = "todos"

                # Si no hay un año seleccionado,
                # las gráficas mensuales mostrarán el actual.
                anio_graficas = (
                    int(anio_solicitado)
                    if anio_solicitado != "todos"
                    else hoy.year
                )

                # --------------------------------------
                # CONSTRUIR FILTROS SEGUROS PARA SQL
                # --------------------------------------

                condiciones = ["p.id_usuario = %s"]
                parametros = [id_admin]

                if anio_solicitado != "todos":
                    condiciones.append("""
                        EXTRACT(YEAR FROM p.fecha_registro)::int = %s
                    """)
                    parametros.append(int(anio_solicitado))

                if categoria_solicitada != "todas":
                    condiciones.append("""
                        EXISTS (
                            SELECT 1
                            FROM public.proveedor_categoria pc_filtro
                            WHERE pc_filtro.id_proveedor = p.id
                              AND pc_filtro.id_categoria = %s
                        )
                    """)
                    parametros.append(int(categoria_solicitada))

                tiene_correo = """
                    NULLIF(BTRIM(p.correo), '') IS NOT NULL
                """

                tiene_telefono = """
                    NULLIF(BTRIM(p.telefono), '') IS NOT NULL
                """

                if contacto_solicitado == "completo":
                    condiciones.append(
                        f"({tiene_correo} AND {tiene_telefono})"
                    )

                elif contacto_solicitado == "parcial":
                    condiciones.append(
                        f"(({tiene_correo}) <> ({tiene_telefono}))"
                    )

                elif contacto_solicitado == "sin":
                    condiciones.append(
                        f"(NOT ({tiene_correo}) AND NOT ({tiene_telefono}))"
                    )

                filtro_sql = " AND ".join(condiciones)
                parametros = tuple(parametros)

                # --------------------------------------
                # INDICADORES DE PROVEEDORES
                # --------------------------------------

                cursor.execute(f"""
                    SELECT
                        COUNT(*) AS total_proveedores,

                        COUNT(*) FILTER (
                            WHERE {tiene_correo}
                        ) AS con_correo,

                        COUNT(*) FILTER (
                            WHERE {tiene_telefono}
                        ) AS con_telefono,

                        COUNT(*) FILTER (
                            WHERE {tiene_correo}
                              AND {tiene_telefono}
                        ) AS contacto_completo,

                        COUNT(*) FILTER (
                            WHERE ({tiene_correo})
                               <> ({tiene_telefono})
                        ) AS contacto_parcial,

                        COUNT(*) FILTER (
                            WHERE NOT ({tiene_correo})
                              AND NOT ({tiene_telefono})
                        ) AS sin_contacto

                    FROM public.proveedor p
                    WHERE {filtro_sql}
                """, parametros)

                indicadores = dict(cursor.fetchone())

                # --------------------------------------
                # PROVEEDORES RECIENTES
                # --------------------------------------

                cursor.execute(f"""
                    SELECT
                        p.id,
                        p.nombre_proveedor,
                        p.nombre_empresa,
                        p.descripcion,
                        p.correo,
                        p.telefono
                    FROM public.proveedor p
                    WHERE {filtro_sql}
                    ORDER BY p.id DESC
                    LIMIT 5
                """, parametros)

                proveedores_recientes = cursor.fetchall()

                # --------------------------------------
                # PROVEEDORES POR CATEGORÍA
                # --------------------------------------

                cursor.execute(f"""
                    WITH proveedores_filtrados AS (
                        SELECT p.id
                        FROM public.proveedor p
                        WHERE {filtro_sql}
                    )
                    SELECT
                        c.nombre AS categoria,
                        COUNT(DISTINCT pf.id) AS total
                    FROM proveedores_filtrados pf
                    INNER JOIN public.proveedor_categoria pc
                        ON pc.id_proveedor = pf.id
                    INNER JOIN public.categorias c
                        ON c.id = pc.id_categoria
                    GROUP BY c.id, c.nombre
                    ORDER BY total DESC, c.nombre ASC
                """, parametros)

                resultados_categorias = cursor.fetchall()

                # --------------------------------------
                # PAGOS PENDIENTES DE LOS PROVEEDORES
                # QUE CUMPLEN LOS FILTROS
                # --------------------------------------

                cursor.execute(f"""
                    SELECT
                        COUNT(*) AS total_pagos_pendientes,
                        COALESCE(SUM(r.monto), 0) AS monto_pendiente
                    FROM public.recordatorios_pago r
                    INNER JOIN public.proveedor p
                        ON p.id = r.id_proveedor
                    WHERE {filtro_sql}
                      AND r.pagado = FALSE
                """, parametros)

                indicadores_pagos = dict(cursor.fetchone())

                # --------------------------------------
                # TABLA DE PAGOS PENDIENTES
                # --------------------------------------

                cursor.execute(f"""
                    SELECT
                        r.id,
                        r.numero_factura,
                        r.monto,
                        r.fecha_vencimiento,
                        p.nombre_proveedor
                    FROM public.recordatorios_pago r
                    INNER JOIN public.proveedor p
                        ON p.id = r.id_proveedor
                    WHERE {filtro_sql}
                      AND r.pagado = FALSE
                    ORDER BY
                        r.fecha_vencimiento ASC,
                        r.id ASC
                    LIMIT 5
                """, parametros)

                pagos_proximos = cursor.fetchall()

                # --------------------------------------
                # CAMPANITA DE NOTIFICACIONES
                # NO SE FILTRA: SE CONSERVAN TODAS
                # LAS ALERTAS DEL ADMINISTRADOR
                # --------------------------------------

                cursor.execute("""
                    SELECT
                        r.id,
                        r.numero_factura,
                        r.monto,
                        r.fecha_vencimiento,
                        p.nombre_proveedor
                    FROM public.recordatorios_pago r
                    INNER JOIN public.proveedor p
                        ON p.id = r.id_proveedor
                    WHERE p.id_usuario = %s
                      AND r.pagado = FALSE
                      AND r.fecha_vencimiento
                          <= CURRENT_DATE + INTERVAL '7 days'
                    ORDER BY
                        r.fecha_vencimiento ASC,
                        r.id ASC
                """, (id_admin,))

                notificaciones_pago = cursor.fetchall()

                # --------------------------------------
                # GRÁFICA: PROVEEDORES POR MES
                # --------------------------------------

                cursor.execute(f"""
                    SELECT
                        EXTRACT(
                            MONTH FROM p.fecha_registro
                        )::int AS mes,
                        COUNT(*)::int AS total
                    FROM public.proveedor p
                    WHERE {filtro_sql}
                      AND EXTRACT(
                          YEAR FROM p.fecha_registro
                      )::int = %s
                    GROUP BY mes
                    ORDER BY mes
                """, parametros + (anio_graficas,))

                registros_mensuales = cursor.fetchall()

                # --------------------------------------
                # GRÁFICA: PAGOS REALIZADOS POR MES
                # --------------------------------------

                cursor.execute(f"""
                    SELECT
                        EXTRACT(
                            MONTH FROM r.fecha_pago
                        )::int AS mes,
                        COALESCE(SUM(r.monto), 0) AS total
                    FROM public.recordatorios_pago r
                    INNER JOIN public.proveedor p
                        ON p.id = r.id_proveedor
                    WHERE {filtro_sql}
                      AND r.pagado = TRUE
                      AND r.fecha_pago IS NOT NULL
                      AND EXTRACT(
                          YEAR FROM r.fecha_pago
                      )::int = %s
                    GROUP BY mes
                    ORDER BY mes
                """, parametros + (anio_graficas,))

                pagos_mensuales = cursor.fetchall()

        # --------------------------------------
        # PREPARAR DATOS PARA CHART.JS
        # --------------------------------------

        nombres_categorias = [
            fila["categoria"]
            for fila in resultados_categorias
        ]

        cantidades_categorias = [
            int(fila["total"])
            for fila in resultados_categorias
        ]

        total_categorias = len(nombres_categorias)

        total = int(indicadores["total_proveedores"])

        porcentaje_contacto = (
            round(
                int(indicadores["contacto_completo"])
                / total * 100,
                1
            )
            if total > 0
            else 0
        )

        proveedores_por_mes = [0] * 12
        pagos_por_mes = [0.0] * 12

        for fila in registros_mensuales:
            mes = int(fila["mes"])
            proveedores_por_mes[mes - 1] = int(fila["total"])

        for fila in pagos_mensuales:
            mes = int(fila["mes"])
            pagos_por_mes[mes - 1] = float(fila["total"])

        # --------------------------------------
        # CLASIFICACIÓN DE FACTURAS
        # --------------------------------------

        for pago in pagos_proximos:

            if pago["fecha_vencimiento"] < hoy:
                pago["estado"] = "Vencido"

            elif pago["fecha_vencimiento"] <= limite_proximo:
                pago["estado"] = "Próximo a vencer"

            else:
                pago["estado"] = "Pendiente"

        # --------------------------------------
        # ENVIAR DATOS AL DASHBOARD
        # --------------------------------------

        return render_template(
            "panel.html",

            usuario=session["usuario"],

            proveedores_recientes=proveedores_recientes,

            nombres_categorias=nombres_categorias,
            cantidades_categorias=cantidades_categorias,
            total_categorias=total_categorias,

            porcentaje_contacto=porcentaje_contacto,

            proveedores_por_mes=proveedores_por_mes,
            pagos_por_mes=pagos_por_mes,

            pagos_proximos=pagos_proximos,

            notificaciones_pago=notificaciones_pago,
            total_notificaciones=len(notificaciones_pago),

            hoy=hoy,
            limite_proximo=limite_proximo,

            # Nuevas variables de los filtros
            periodo_seleccionado=anio_solicitado,
            categoria_seleccionada=categoria_solicitada,
            contacto_seleccionado=contacto_solicitado,
            anios_disponibles=anios_disponibles,
            categorias_disponibles=categorias_disponibles,
            anio_graficas=anio_graficas,

            **indicadores,
            **indicadores_pagos
        )

    except psycopg2.Error as e:
        print("Error al cargar el panel:", e)
        return "Error al cargar el panel.", 500

# ==========================================
# MIS PROVEEDORES
# FUNCIÓN QUE FALTABA
# ==========================================

@app.route("/proveedores")
@login_requerido
def mis_proveedores():

    id_admin = session["id_usuario"]

    busqueda = request.args.get("buscar", "").strip()

    try:
        with conectar_bd() as conexion:
            with conexion.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                if busqueda:

                    dato = f"%{busqueda}%"

                    cursor.execute("""
                        SELECT *
                        FROM public.proveedor

                        WHERE id_usuario = %s
                          AND (
                              nombre_proveedor ILIKE %s
                              OR nombre_empresa ILIKE %s
                              OR descripcion ILIKE %s
                              OR telefono ILIKE %s
                              OR correo ILIKE %s
                          )

                        ORDER BY nombre_proveedor ASC
                    """, (
                        id_admin,
                        dato,
                        dato,
                        dato,
                        dato,
                        dato
                    ))

                else:

                    cursor.execute("""
                        SELECT *
                        FROM public.proveedor
                        WHERE id_usuario = %s
                        ORDER BY nombre_proveedor ASC
                    """, (id_admin,))

                proveedores = cursor.fetchall()

        return render_template(
            "proveedores.html",
            proveedores=proveedores,
            usuario=session["usuario"]
        )

    except psycopg2.Error as e:
        print("Error al consultar proveedores:", e)

        return (
            "No se pudieron consultar los proveedores.",
            500
        )


# ==========================================
# BUSCADOR INTERNO
# ==========================================

@app.route("/buscar")
@login_requerido
def buscar():

    return redirect(url_for("mis_proveedores"))


# ==========================================
# API DEL BUSCADOR
# ==========================================

@app.route("/buscar_api")
@login_requerido
def buscar_api():

    busqueda = request.args.get("buscar", "").strip()
    id_admin = session["id_usuario"]

    try:
        with conectar_bd() as conexion:
            with conexion.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                if busqueda:

                    dato = f"%{busqueda}%"

                    cursor.execute("""
                        SELECT *
                        FROM public.proveedor

                        WHERE id_usuario = %s
                          AND (
                              nombre_proveedor ILIKE %s
                              OR nombre_empresa ILIKE %s
                              OR descripcion ILIKE %s
                              OR telefono ILIKE %s
                              OR correo ILIKE %s
                          )

                        ORDER BY nombre_proveedor
                    """, (
                        id_admin,
                        dato,
                        dato,
                        dato,
                        dato,
                        dato
                    ))

                else:

                    cursor.execute("""
                        SELECT *
                        FROM public.proveedor
                        WHERE id_usuario = %s
                        ORDER BY nombre_proveedor
                    """, (id_admin,))

                proveedores = cursor.fetchall()

        return jsonify(proveedores)

    except psycopg2.Error as e:
        print("Error en buscador:", e)

        return jsonify({
            "error": "No se pudieron consultar los proveedores."
        }), 500
    

# ==========================================
# PÁGINA PARA BUSCAR PROVEEDORES
# ==========================================

@app.route("/buscar-proveedores")
@login_requerido
def buscar_proveedores():
    return render_template(
        "buscar.html",
        usuario=session["usuario"]
    )

# ==========================================
# AGREGAR PROVEEDOR CON CATEGORÍAS
# ==========================================

@app.route("/agregar", methods=["GET", "POST"])
@login_requerido
def agregar_provider():

    id_admin = session["id_usuario"]

    try:
        with conectar_bd() as conexion:
            with conexion.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                cursor.execute("""
                    SELECT id, nombre
                    FROM public.categorias
                    ORDER BY nombre ASC
                """)

                categorias = cursor.fetchall()

                if request.method == "POST":

                    nombre = request.form.get(
                        "nombre", ""
                    ).strip()

                    empresa = request.form.get(
                        "empresa", ""
                    ).strip()

                    telefono = request.form.get(
                        "telefono", ""
                    ).strip()

                    correo = request.form.get(
                        "correo", ""
                    ).strip()

                    descripcion = request.form.get(
                        "descripcion", ""
                    ).strip()

                    categorias_formulario = request.form.getlist(
                        "categorias"
                    )

                    if not nombre:
                        return (
                            "El nombre del proveedor es obligatorio.",
                            400
                        )

                    try:
                        ids_categorias = list({
                            int(valor)
                            for valor in categorias_formulario
                        })

                    except ValueError:
                        return "Categoría inválida.", 400

                    ids_validos = {
                        categoria["id"]
                        for categoria in categorias
                    }

                    if not set(ids_categorias).issubset(ids_validos):
                        return "Una categoría no existe.", 400

                    cursor.execute("""
                        INSERT INTO public.proveedor (
                            nombre_proveedor,
                            nombre_empresa,
                            telefono,
                            correo,
                            descripcion,
                            id_usuario
                        )

                        VALUES (%s, %s, %s, %s, %s, %s)
                        RETURNING id
                    """, (
                        nombre,
                        empresa,
                        telefono,
                        correo,
                        descripcion,
                        id_admin
                    ))

                    nuevo_proveedor = cursor.fetchone()["id"]

                    for id_categoria in ids_categorias:

                        cursor.execute("""
                            INSERT INTO public.proveedor_categoria (
                                id_proveedor,
                                id_categoria
                            )

                            VALUES (%s, %s)
                        """, (
                            nuevo_proveedor,
                            id_categoria
                        ))

        if request.method == "POST":
            return redirect(url_for("mis_proveedores"))

        return render_template(
            "agregar.html",
            categorias=categorias
        )

    except psycopg2.Error as e:
        print("Error al agregar proveedor:", e)
        return "Error al procesar el proveedor.", 500


# ==========================================
# EDITAR PROVEEDOR
# ==========================================

@app.route("/editar/<int:id>", methods=["GET", "POST"])
@login_requerido
def editar_proveedor(id):

    id_admin = session["id_usuario"]

    try:
        with conectar_bd() as conexion:
            with conexion.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                cursor.execute("""
                    SELECT *
                    FROM public.proveedor
                    WHERE id = %s
                      AND id_usuario = %s
                """, (id, id_admin))

                proveedor = cursor.fetchone()

                if not proveedor:
                    return "Proveedor no encontrado.", 404

                cursor.execute("""
                    SELECT id, nombre
                    FROM public.categorias
                    ORDER BY nombre ASC
                """)

                categorias = cursor.fetchall()

                cursor.execute("""
                    SELECT id_categoria
                    FROM public.proveedor_categoria
                    WHERE id_proveedor = %s
                """, (id,))

                categorias_seleccionadas = [
                    fila["id_categoria"]
                    for fila in cursor.fetchall()
                ]

                if request.method == "POST":

                    nombre = request.form.get(
                        "nombre", ""
                    ).strip()

                    empresa = request.form.get(
                        "empresa", ""
                    ).strip()

                    telefono = request.form.get(
                        "telefono", ""
                    ).strip()

                    correo = request.form.get(
                        "correo", ""
                    ).strip()

                    descripcion = request.form.get(
                        "descripcion", ""
                    ).strip()

                    categorias_formulario = request.form.getlist(
                        "categorias"
                    )

                    if not nombre:
                        return (
                            "El nombre del proveedor es obligatorio.",
                            400
                        )

                    try:
                        ids_categorias = list({
                            int(valor)
                            for valor in categorias_formulario
                        })

                    except ValueError:
                        return "Categoría inválida.", 400

                    ids_validos = {
                        categoria["id"]
                        for categoria in categorias
                    }

                    if not set(ids_categorias).issubset(ids_validos):
                        return "Una categoría no existe.", 400

                    cursor.execute("""
                        UPDATE public.proveedor
                        SET
                            nombre_proveedor = %s,
                            nombre_empresa = %s,
                            telefono = %s,
                            correo = %s,
                            descripcion = %s

                        WHERE id = %s
                          AND id_usuario = %s
                    """, (
                        nombre,
                        empresa,
                        telefono,
                        correo,
                        descripcion,
                        id,
                        id_admin
                    ))

                    cursor.execute("""
                        DELETE FROM public.proveedor_categoria
                        WHERE id_proveedor = %s
                    """, (id,))

                    for id_categoria in ids_categorias:

                        cursor.execute("""
                            INSERT INTO public.proveedor_categoria (
                                id_proveedor,
                                id_categoria
                            )

                            VALUES (%s, %s)
                        """, (
                            id,
                            id_categoria
                        ))

                else:

                    return render_template(
                        "editar.html",
                        p=proveedor,
                        categorias=categorias,
                        categorias_seleccionadas=categorias_seleccionadas
                    )

        return redirect(url_for("mis_proveedores"))

    except psycopg2.Error as e:
        print("Error al editar proveedor:", e)
        return "Error al actualizar proveedor.", 500


# ==========================================
# ELIMINAR PROVEEDOR
# ==========================================

@app.route("/eliminar/<int:id>", methods=["POST"])
@login_requerido
def eliminar_proveedor(id):

    id_admin = session["id_usuario"]

    try:
        with conectar_bd() as conexion:
            with conexion.cursor() as cursor:

                cursor.execute("""
                    DELETE FROM public.proveedor
                    WHERE id = %s
                      AND id_usuario = %s
                """, (id, id_admin))

        return redirect(url_for("mis_proveedores"))

    except psycopg2.Error as e:
        print("Error al eliminar proveedor:", e)
        return "Error al eliminar proveedor.", 500


# ==========================================
# CAMBIAR CONTRASEÑA
# ==========================================

@app.route(
    "/restablecer_contrasena",
    methods=["GET", "POST"]
)
@login_requerido
def restablecer_contrasena():

    error = None
    exito = None

    if request.method == "POST":

        actual = request.form.get("actual", "")
        nueva = request.form.get("nueva", "")
        confirmar = request.form.get("confirmar", "")

        if not actual:
            error = "Ingresa tu contraseña actual."

        elif len(nueva) < 12:
            error = (
                "La nueva contraseña debe tener "
                "al menos 12 caracteres."
            )

        elif nueva != confirmar:
            error = "Las contraseñas no coinciden."

        else:

            try:
                with conectar_bd() as conexion:
                    with conexion.cursor(
                        cursor_factory=RealDictCursor
                    ) as cursor:

                        cursor.execute("""
                            SELECT contrasena
                            FROM public.usuario
                            WHERE id = %s
                        """, (session["id_usuario"],))

                        datos = cursor.fetchone()

                        if not datos:
                            error = "Usuario no encontrado."

                        else:

                            guardada = datos["contrasena"]

                            if guardada.startswith(
                                ("scrypt:", "pbkdf2:")
                            ):
                                valida = check_password_hash(
                                    guardada,
                                    actual
                                )
                            else:
                                valida = guardada == actual

                            if not valida:
                                error = "Contraseña actual incorrecta."

                            else:

                                nueva_hash = generate_password_hash(
                                    nueva
                                )

                                cursor.execute("""
                                    UPDATE public.usuario
                                    SET contrasena = %s
                                    WHERE id = %s
                                """, (
                                    nueva_hash,
                                    session["id_usuario"]
                                ))

                                exito = (
                                    "Contraseña actualizada correctamente."
                                )

            except psycopg2.Error as e:
                print("Error al cambiar contraseña:", e)
                error = "No se pudo actualizar la contraseña."

    return render_template(
        "restablecer_contrasena.html",
        error=error,
        exito=exito
    )


# ==========================================
# SEGURIDAD DE FORMULARIOS DE PAGOS
# ==========================================

def token_formulario():

    if "csrf_pagos" not in session:
        session["csrf_pagos"] = secrets.token_urlsafe(32)

    return session["csrf_pagos"]


def validar_token_pago():

    recibido = request.form.get("csrf_token", "")
    esperado = session.get("csrf_pagos", "")

    return bool(
        recibido
        and esperado
        and secrets.compare_digest(recibido, esperado)
    )


# ==========================================
# VALIDAR DATOS DE FACTURAS
# ==========================================

def validar_datos_factura(formulario, proveedores):

    try:
        id_proveedor = int(
            formulario.get("id_proveedor", "")
        )

        numero = formulario.get(
            "numero_factura", ""
        ).strip()

        monto = Decimal(
            formulario.get("monto", "")
        )

        vencimiento = date.fromisoformat(
            formulario.get("fecha_vencimiento", "")
        )

        if not numero or len(numero) > 100:
            raise ValueError("Número de factura inválido.")

        if (
            not monto.is_finite()
            or monto < 0
            or monto > Decimal("9999999999.99")
            or monto.as_tuple().exponent < -2
        ):
            raise ValueError("Monto inválido.")

        ids_validos = {
            proveedor["id"]
            for proveedor in proveedores
        }

        if id_proveedor not in ids_validos:
            raise ValueError("Proveedor inválido.")

        return {
            "id_proveedor": id_proveedor,
            "numero_factura": numero,
            "monto": monto,
            "fecha_vencimiento": vencimiento
        }

    except (
        ValueError,
        InvalidOperation,
        OverflowError,
        TypeError
    ):
        return None


# ==========================================
# ESTADO AUTOMÁTICO DE PAGOS
# ==========================================

def estado_pago(pago, hoy=None):

    if hoy is None:
        hoy = date.today()

    if pago["pagado"]:
        return "Pagado"

    if pago["fecha_vencimiento"] < hoy:
        return "Vencido"

    if pago["fecha_vencimiento"] <= hoy + timedelta(days=7):
        return "Próximo a vencer"

    return "Pendiente"


# ==========================================
# RECORDATORIOS DE PAGOS
# ==========================================

@app.route("/recordatorios", methods=["GET", "POST"])
@login_requerido
def recordatorios():

    id_admin = session["id_usuario"]
    error = None

    try:
        with conectar_bd() as conexion:
            with conexion.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                # PROVEEDORES DEL USUARIO

                cursor.execute("""
                    SELECT
                        id,
                        nombre_proveedor,
                        nombre_empresa

                    FROM public.proveedor

                    WHERE id_usuario = %s
                    ORDER BY nombre_proveedor ASC
                """, (id_admin,))

                proveedores = cursor.fetchall()

                # REGISTRAR NUEVA FACTURA

                if request.method == "POST":

                    if not validar_token_pago():
                        return (
                            "Formulario inválido. Actualiza la página.",
                            400
                        )

                    datos = validar_datos_factura(
                        request.form,
                        proveedores
                    )

                    if not datos:

                        error = (
                            "Revisa el proveedor, número de factura, "
                            "monto y fecha de vencimiento."
                        )

                    else:

                        cursor.execute("""
                            INSERT INTO public.recordatorios_pago (
                                id_proveedor,
                                numero_factura,
                                monto,
                                fecha_vencimiento
                            )

                            VALUES (%s, %s, %s, %s)
                        """, (
                            datos["id_proveedor"],
                            datos["numero_factura"],
                            datos["monto"],
                            datos["fecha_vencimiento"]
                        ))

                # CONSULTAR TODAS LAS FACTURAS

                cursor.execute("""
                    SELECT
                        r.id,
                        r.id_proveedor,
                        r.numero_factura,
                        r.monto,
                        r.fecha_vencimiento,
                        r.pagado,
                        r.fecha_pago,
                        p.nombre_proveedor,
                        p.nombre_empresa

                    FROM public.recordatorios_pago r

                    JOIN public.proveedor p
                        ON p.id = r.id_proveedor

                    WHERE p.id_usuario = %s

                    ORDER BY
                        r.pagado ASC,
                        r.fecha_vencimiento ASC,
                        r.id DESC
                """, (id_admin,))

                pagos = cursor.fetchall()

        if request.method == "POST" and not error:
            return redirect(url_for("recordatorios"))

        hoy = date.today()

        for pago in pagos:
            pago["estado"] = estado_pago(pago, hoy)

        return render_template(
            "recordatorios.html",
            usuario=session["usuario"],
            proveedores=proveedores,
            pagos=pagos,
            error=error,
            csrf_token=token_formulario(),
            hoy=hoy
        )

    except psycopg2.Error as e:
        print("Error en recordatorios:", e)

        return (
            "No se pudieron cargar los recordatorios.",
            500
        )


# ==========================================
# EDITAR RECORDATORIO
# ==========================================

@app.route(
    "/recordatorios/<int:id_pago>/editar",
    methods=["GET", "POST"]
)
@login_requerido
def editar_recordatorio(id_pago):

    id_admin = session["id_usuario"]
    error = None

    try:
        with conectar_bd() as conexion:
            with conexion.cursor(
                cursor_factory=RealDictCursor
            ) as cursor:

                # COMPROBAR PROPIEDAD DEL RECORDATORIO

                cursor.execute("""
                    SELECT r.*
                    FROM public.recordatorios_pago r

                    JOIN public.proveedor p
                        ON p.id = r.id_proveedor

                    WHERE r.id = %s
                      AND p.id_usuario = %s
                """, (id_pago, id_admin))

                pago = cursor.fetchone()

                if not pago:
                    return "Recordatorio no encontrado.", 404

                # PROVEEDORES DISPONIBLES

                cursor.execute("""
                    SELECT
                        id,
                        nombre_proveedor,
                        nombre_empresa

                    FROM public.proveedor

                    WHERE id_usuario = %s
                    ORDER BY nombre_proveedor ASC
                """, (id_admin,))

                proveedores = cursor.fetchall()

                # GUARDAR CAMBIOS

                if request.method == "POST":

                    if not validar_token_pago():
                        return "Formulario inválido.", 400

                    datos = validar_datos_factura(
                        request.form,
                        proveedores
                    )

                    if not datos:

                        error = (
                            "Revisa los datos del recordatorio."
                        )

                    else:

                        cursor.execute("""
                            UPDATE public.recordatorios_pago r

                            SET
                                id_proveedor = %s,
                                numero_factura = %s,
                                monto = %s,
                                fecha_vencimiento = %s

                            FROM public.proveedor p

                            WHERE r.id = %s
                              AND r.id_proveedor = p.id
                              AND p.id_usuario = %s
                        """, (
                            datos["id_proveedor"],
                            datos["numero_factura"],
                            datos["monto"],
                            datos["fecha_vencimiento"],
                            id_pago,
                            id_admin
                        ))

                else:

                    return render_template(
                        "editar_recordatorio.html",
                        usuario=session["usuario"],
                        pago=pago,
                        proveedores=proveedores,
                        error=error,
                        csrf_token=token_formulario()
                    )

        if request.method == "POST" and not error:
            return redirect(url_for("recordatorios"))

        return render_template(
            "editar_recordatorio.html",
            usuario=session["usuario"],
            pago=pago,
            proveedores=proveedores,
            error=error,
            csrf_token=token_formulario()
        )

    except psycopg2.Error as e:
        print("Error al editar recordatorio:", e)
        return "No se pudo editar el recordatorio.", 500


# ==========================================
# MARCAR FACTURA PAGADA O REABRIR
# ==========================================

@app.route(
    "/recordatorios/<int:id_pago>/estado",
    methods=["POST"]
)
@login_requerido
def cambiar_estado_recordatorio(id_pago):

    if not validar_token_pago():
        return "Formulario inválido.", 400

    accion = request.form.get("accion")

    if accion not in ("pagar", "reabrir"):
        return "Acción inválida.", 400

    pagado = accion == "pagar"

    try:
        with conectar_bd() as conexion:
            with conexion.cursor() as cursor:

                cursor.execute("""
                    UPDATE public.recordatorios_pago r

                    SET
                        pagado = %s,

                        fecha_pago = CASE
                            WHEN %s THEN CURRENT_DATE
                            ELSE NULL
                        END

                    FROM public.proveedor p

                    WHERE r.id = %s
                      AND r.id_proveedor = p.id
                      AND p.id_usuario = %s
                """, (
                    pagado,
                    pagado,
                    id_pago,
                    session["id_usuario"]
                ))

        return redirect(url_for("recordatorios"))

    except psycopg2.Error as e:
        print("Error al cambiar estado:", e)
        return "No se pudo cambiar el estado.", 500


# ==========================================
# ELIMINAR RECORDATORIO
# ==========================================

@app.route(
    "/recordatorios/<int:id_pago>/eliminar",
    methods=["POST"]
)
@login_requerido
def eliminar_recordatorio(id_pago):

    if not validar_token_pago():
        return "Formulario inválido.", 400

    try:
        with conectar_bd() as conexion:
            with conexion.cursor() as cursor:

                cursor.execute("""
                    DELETE FROM public.recordatorios_pago r

                    USING public.proveedor p

                    WHERE r.id = %s
                      AND r.id_proveedor = p.id
                      AND p.id_usuario = %s
                """, (
                    id_pago,
                    session["id_usuario"]
                ))

        return redirect(url_for("recordatorios"))

    except psycopg2.Error as e:
        print("Error al eliminar recordatorio:", e)
        return "No se pudo eliminar el recordatorio.", 500


# ==========================================
# CERRAR SESIÓN
# ==========================================

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))


# ==========================================
# FAVICON
# ==========================================

@app.route("/favicon.ico")
def favicon():

    return "", 204


# ==========================================
# EJECUTAR APLICACIÓN
# ==========================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
