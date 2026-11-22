# Formatos de Darksiders II Deathinitive Edition (PC)

Notas de ingeniería inversa usadas por DDWExtractor. Todos los enteros son little endian.
Los "nombres" con hash usan CRC64 (polinomio `0x01A1561E0005800C`, valor inicial y XOR
final `0xFFFFFFFFFFFFFFFF`, tabla reflejada).

## Carpeta `media`

| Archivo | Contenido |
|---|---|
| `manifest.bin` | Índice de todos los recursos |
| `media.upak`, `maps.upak` | Contenedores OBPK concatenados, alineados a 0x800 |
| `anim_streams.upak` | Animaciones en streaming (zlib) |
| `scripts.obsp` | Datos de gameplay (objetos BOD) |

### manifest.bin (versión 13)

```
u32 version
40 bytes
u32 n_carpetas, u32 (sin uso)
n_carpetas x { u64 hash, u32 len, char[len] ruta }
u32 n_paks
n_paks x { u8, u16 len, char[len] nombre }          "media", "maps"...
u32 n_recursos
n_recursos x {
    u8 len, char[len] nombre, u64 hash,
    u16 package_id, u16 indice_carpeta,
    u8 align, align*2 bytes, u8, u8 indice_pak, 2 bytes,
    u64 offset (u32 si version < 13)
}
```

El tamaño de un recurso es la distancia al siguiente recurso del mismo `.upak`.

## Contenedor OBPK

```
0x00  "OBPK"
0x04  u8   0 = little endian
0x05  u32  versión (9)
0x09  u32  offset sección A, 0x0D u32 tamaño A
0x11  u32  offset sección B, 0x15 u32 tamaño B
0x19  u32  inicio de datos (múltiplo de 0x800)
```

Sección A (tabla de recursos):

```
u32 n_grupos, u32 n_entradas, u32 tam_blob, u32
blob[tam_blob]                 hashes y pares u16 por entrada
4 x u32
n_grupos x { u32 tipo, u32 n, u32 off_hashes, u32 off_u16, u8 flags[n] }
u8 hay_nombres, u32 long_max
por grupo, n x { u64 hash, u32 len, char[len] }
```

Tipos de grupo: 0 efectos, 1 modelos (`Object3D`), 2 mallas, 5 materiales, 6 texturas,
8 animaciones, 9 sonido, 11 tela/física, 20 esqueleto.

Datos: secuencia de bloques `{ u32 tamaño_descomprimido, stream zlib }`. Concatenados
forman el *payload*. Los recursos aparecen en el payload en el orden de la tabla.

## Objetos BOD

`"BOD\xFD"`, u8 modo (4), 3 bytes, u32, u32, y un objeto raíz.

Objeto: `u8 tipo` (0 = nulo; 4 = 4 bytes extra), nombre de clase, `u32 n`, y n veces
`nombre_propiedad, valor`.

Nombre: `u8 1, u64 hash, u16 len, char[len]` la primera vez (se agrega a una lista por
blob) o `u8 0, u32 índice` después.

Valores (etiqueta u8): `00` nulo, `02` i32, `03` f32, `04` bool, `05 FF u16 len` texto,
`07 u32` + objeto, `09`/`0A` `u32 n, u8 es_mapa` + elementos (o pares), `0B u32 n`
lista, `0D` u64, `0F` nombre, `FC u32 id, u64 hash` referencia.

Clases útiles: `Material` (`Name`, `ShaderName`, `Parameters` → `DiffuseMap1`,
`NormalMap1`, `SpecularMap1`, `EmissiveMap1` → `Value` = nombre de textura), `Object3D`
(`Skeleton`, `Visuals`), `Skeleton3D`/`Node3D` (`Name`, `Position`, `Rotation`,
`Children`), `SkinMeshVisual` / `StaticMeshVisual` (`MeshName`, `MeshID`, `RefNode`).

## Mallas

```
u32 desconocido
u32 n_partes, u32 n_partes, u32 n_indices[n]
u32 n_partes, i32 n_vertices[n]        >0 con esqueleto, <0 estática
i32 -n_partes
n x (u32, u32)                         estática: (n_vertices, f32 0.5); esqueleto: (0, 0)
n x cabecera_de_parte
n x datos_de_parte
```

Cabecera de parte:

```
u8  con_esqueleto
u32 n_vertices, u32 stride_gpu (64 / 60), u32 offset_indices (relativo al inicio de datos)
con esqueleto: u32 n_submallas, u32 n_huesos     estática: u32 (2), u32 n_submallas
6 x f32 caja (min, max)
con esqueleto: n_huesos x { nombre, 16 x f32 matriz inversa de bind, u32 id }
n_submallas x { nombre_material, i32 id, u32 0, u32 n_vertices, u32 vertice_base,
                u32 n_indices, u32 primer_indice }
```

(`nombre` = `FF, u16 len, ascii`.)

Datos de parte:

```
u32 bytes_indices, u32 tamaño_indice (2 o 4), índices (lista de triángulos, globales a la parte)
con esqueleto:
    n x 20 B  { f32 u, f32 v, u32 0, u32 0, i32 -1 }
    n x 52 B  { u32, f32 x y z, f32 1.0, f32 normal[3], f32 tangente[4], f32 signo }
    n x 16 B  pesos (4 x f32)
    n x  4 B  índices de hueso (4 x u8)
estática:
    n x 12 B  f32 x y z
    n x 48 B  { normal[3], tangente[3], signo, f32 u, f32 v, u32 0, u32 0, i32 -1 }
    n x 16 B
```

Matrices en convención de vector fila (traslación en la última fila). Espacio del juego:
Z hacia arriba. Death mide unas 64 unidades.

Las partes estáticas están en el espacio local del hueso `RefNode` de su
`StaticMeshVisual`. Su transformación sale de la matriz de bind del hueso (si alguna parte
con esqueleto lo usa) o del esqueleto. Rotaciones de `Node3D`: grados, aplicadas X, luego Y
y luego Z (`R = Rx·Ry·Rz`, vector fila). Las armas usan el esqueleto de `characters/death`.

## Texturas

Archivos DDS completos (`"DDS "`, DXT1/DXT5) dentro del payload, en el mismo orden que el
grupo de texturas de la tabla.
