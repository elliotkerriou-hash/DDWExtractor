# DDWExtractor

Herramienta hecha por fans para extraer los **modelos 3D y texturas** de tu propia copia de
**Darksiders II Deathinitive Edition**, para usarlos como referencia en cosplay, figuras,
impresión 3D y fan art.

*English version: [README.md](README.md)*

> **Importante:** este proyecto **no incluye ningún archivo del juego**. Cada persona
> extrae los modelos de su propia copia legal. Por favor **no compartas los archivos
> extraídos**: pertenecen a THQ Nordic. Comparte la herramienta, no los modelos.

## Qué extrae

- Modelos **OBJ** (estáticos): se abren en cualquier programa 3D o slicer (Blender, ZBrush, Cura…).
- Modelos **GLB** (glTF 2.0) **con esqueleto y pesos**, para posarlos en Blender
  (Archivo > Importar > glTF 2.0). Las texturas van incluidas.
- Texturas **PNG** (color, normales, especular, emisivas), enlazadas en el `.mtl` del OBJ.
- Personajes, armaduras, armas, enemigos, jefes, NPCs y escenarios.

| Recurso | Contenido |
|---|---|
| `characters/death` | Cabeza y máscara de Death, forma Reaper y su guadaña |
| `items/armor` | 205 piezas: cuerpo base y todos los sets (cuerpo, guantes, botas, hombreras) |
| `items/weapons` | 197 armas: guadañas, guadañas dobles, martillos, hachas, guanteletes… |
| `characters/despair`, `characters/dust` | El caballo y el cuervo de Death |
| `characters/vulgrim`, `characters/crow_father`, `characters/dark_war`… | NPCs, War y jefes |

Todas las piezas de Death comparten el mismo sistema de coordenadas: cabeza, cuerpo base y
un set de armadura encajan solos.

## Instalación

1. Instala [Python 3.10 o superior](https://www.python.org/downloads/) (marca "Add Python to PATH").
2. En la carpeta del proyecto ejecuta: `pip install -r requirements.txt`

## Uso con ventana (recomendado)

Doble clic en `DDWExtractor.pyw` (o `python -m ddwextractor`). La interfaz está en inglés:

1. El juego se detecta solo; si no, pulsa **Browse…**.
2. Haz clic en un recurso (por ejemplo **Armor**) para abrir la **vista previa** con la
   lista de sus modelos y un buscador.
3. Selecciona uno o varios modelos (Ctrl/Shift + clic). Arrastra para girar, rueda para
   zoom, doble clic para reiniciar. Abajo ves las medidas (en cm si pones tu altura en
   *Scale to my height*).
4. **In-game look** dibuja con texturas completas, sombreado suave, transparencias (pelo,
   telas) y brillo, como en el juego. Al arrastrar se usa una vista rápida.
5. **Extract selected models** guarda solo lo que ves; **Extract selected assets** guarda
   recursos completos. Elige el formato: OBJ, GLB o ambos.

**Hide effects (VFX)** oculta piezas de efectos (fuego, auras, formas fantasma).

## Uso por consola

```
python -m ddwextractor list -m
python -m ddwextractor extract characters/death
python -m ddwextractor extract items/armor --mesh "wanderer*,base_*" --format glb
python -m ddwextractor extract items/weapons --mesh "*scythe*" --height 180
```

Opciones: `-o CARPETA`, `--mesh PATRONES`, `--format obj|glb|both`, `--height CM`,
`--all-textures`, `--combine`, `--scale N`, y `--game CARPETA` antes del comando.

### Escala para cosplay

Death mide unas **64 unidades**. Con `--height 180` (o *Scale to my height* = 180) los
modelos salen en **centímetros para una persona de 180 cm** (OBJ). Los GLB usan metros, como
exige glTF, así que en Blender el mismo modelo mide 1.80 m. La mayoría de slicers leen los
números del OBJ como milímetros: elige centímetros al importar o escala ×10. Death tiene
proporciones exageradas, así que ajusta cada pieza a tus medidas reales.

### Posar en Blender

Importa el `.glb`, selecciona el esqueleto, pasa a *Pose Mode* y rota los huesos. Las hojas
de las armas siguen al hueso de su mango.

## Estado

- **Darksiders II Deathinitive Edition:** modelos, esqueletos y pesos (GLB), texturas y materiales.
- **Darksiders Warmastered Edition (DS1):** en desarrollo.

Notas técnicas del formato: [docs/format_ds2.es.md](docs/format_ds2.es.md) /
[docs/format_ds2.md](docs/format_ds2.md).

## Créditos

- El conocimiento del formato se apoya en investigación pública de la comunidad, en especial
  el [Darksiders 2 Modkit](https://github.com/Kierak1/Darksiders-2-Modkit) de Kierak1 y los
  hilos de ZenHAX/ResHax. El código de este proyecto es una implementación propia.
- Darksiders es una marca de THQ Nordic. Este proyecto no está afiliado a THQ Nordic.

## Licencia

El código se publica bajo la [licencia MIT](LICENSE). Cubre solo el código, no los archivos
del juego ni lo que se extraiga de ellos.
