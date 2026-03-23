"""
Personal Assistant — main entry point.

Usage:
    python main.py claude    # Run with Claude (claude-opus-4-6)
    python main.py openai    # Run with OpenAI (gpt-4o)
    python main.py compare   # Print evaluation comparison
"""
import sys

COMPARISON = """
╔══════════════════════════════════════════════════════════════════════════╗
║          EVALUACIÓN: Claude vs OpenAI para Asistente Personal           ║
╠══════════════════════════════════════════════════════════════════════════╣
║                                                                          ║
║  CRITERIO              CLAUDE (opus-4-6)        OPENAI (gpt-4o)         ║
║  ──────────────────────────────────────────────────────────────────────  ║
║  Razonamiento          ★★★★★  Adaptive          ★★★★☆  CoT implícito   ║
║                        thinking nativo                                   ║
║                                                                          ║
║  Uso de herramientas   ★★★★★  Muy preciso,       ★★★★☆  Robusto,       ║
║                        tool_use nativo           function calling GA     ║
║                                                                          ║
║  Contexto largo        ★★★★★  200K tokens        ★★★★☆  128K tokens    ║
║                        (1M en beta)              (gpt-4o)               ║
║                                                                          ║
║  Costo (input/1M)      $5.00 (Opus 4.6)         $2.50 (gpt-4o)          ║
║  Costo (output/1M)     $25.00                   $10.00                  ║
║                                                                          ║
║  Velocidad             Moderada (streaming)      Rápida (streaming)     ║
║                                                                          ║
║  Idioma español        ★★★★★  Excelente          ★★★★☆  Muy bueno      ║
║                                                                          ║
║  Privacidad/Control    Anthropic API             OpenAI API              ║
║                        (datos no se usan         (revisar TOS para      ║
║                         para entrenamiento)       uso de datos)          ║
║                                                                          ║
║  Personalidad          Muy natural, empática     Directa, eficiente     ║
║                                                                          ║
╠══════════════════════════════════════════════════════════════════════════╣
║  VENTAJAS CLAUDE                                                         ║
║  • Adaptive thinking: razona internamente antes de responder             ║
║  • Mejor manejo de instrucciones complejas y ambiguas                    ║
║  • Contexto de conversación más largo y coherente                        ║
║  • Mayor control sobre el comportamiento (system prompt)                 ║
║  • Respuestas más naturales y empáticas en español                       ║
║                                                                          ║
║  VENTAJAS OPENAI                                                         ║
║  • Menor costo por token (50% menos)                                     ║
║  • Mayor velocidad de respuesta                                          ║
║  • Ecosistema más maduro (Assistants API, threads, etc.)                 ║
║  • Más modelos disponibles para escalar (gpt-4o-mini para tareas simples)║
║                                                                          ║
╠══════════════════════════════════════════════════════════════════════════╣
║  RECOMENDACIÓN FINAL                                                     ║
║                                                                          ║
║  Para un asistente personal de uso intensivo con tareas complejas        ║
║  → CLAUDE OPUS 4.6: mejor razonamiento, coherencia y español             ║
║                                                                          ║
║  Para alto volumen de solicitudes simples con bajo presupuesto            ║
║  → OPENAI GPT-4o-mini: escala bien y cuesta menos                        ║
║                                                                          ║
║  Estrategia híbrida posible: Claude para análisis complejos,             ║
║  OpenAI para operaciones CRUD simples (añadir tarea, etc.)               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("claude", "openai", "compare"):
        print(__doc__)
        print("Opciones: claude | openai | compare")
        sys.exit(1)

    mode = sys.argv[1]

    if mode == "compare":
        print(COMPARISON)

    elif mode == "claude":
        try:
            from agent_claude import run
        except ImportError as e:
            print(f"Error: {e}\nInstala dependencias: pip install anthropic")
            sys.exit(1)
        run()

    elif mode == "openai":
        try:
            from agent_openai import run
        except ImportError as e:
            print(f"Error: {e}\nInstala dependencias: pip install openai")
            sys.exit(1)
        run()


if __name__ == "__main__":
    main()
