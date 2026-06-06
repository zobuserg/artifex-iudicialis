"""
Artifex Iudicialis — la "fábrica de resoluciones".

Arquitectura nueva (LangGraph + Pydantic + RAG) que se construye AL LADO del
motor actual de Adiutor Iudicis (app/core/claude_worker.py). El motor antiguo
no se toca: sigue funcionando igual. La fábrica reutiliza las funciones puras
de app/core (lectura de archivos, bloques de prompt, bibliografía, validación)
pero las orquesta como una cinta transportadora con puntos de control del juez.

Estado de construcción:
  [A] state.py  — la caja Pydantic que viaja la cinta  ← EN CURSO
  [B] nodos     — resumen → fuentes → redacción → verificación → pulido
  [C] graph     — grafo LangGraph con interrupt() en los 3 checkpoints
  [D] ui        — pestaña nueva que maneja el grafo
"""
