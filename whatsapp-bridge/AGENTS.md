# Regla de envíos de WhatsApp

- Todos los envíos deben pasar por `outboundMessages.send` en `main.go`.
- Mantener una pausa global mínima de cinco segundos después de cada intento de envío,
  incluso si falla, para todos los destinatarios y tipos de mensaje.
- Serializar los envíos concurrentes. No saltarse el límite desde scripts, herramientas
  ni nuevos puntos de envío. Conservar las pruebas de intervalo y concurrencia.
- En lotes, esperar la respuesta de cada solicitud antes de enviar la siguiente.
- Máximo treinta destinatarios privados nuevos en una ventana móvil de 24 horas
  y cinco en una ventana móvil de una hora, solicitado por el dueño el 05/10/2026.
  Nuevo significa sin nombre guardado en la agenda y sin mensajes recibidos en ese chat.
  Los nombres de perfil/comercio de WhatsApp no equivalen a un contacto guardado.
- Solo un primer intento por número nuevo hasta recibir respuesta; no reintentar
  automáticamente fallos ni cambiar entre teléfono y LID para eludir el límite.
  El registro persiste en `store/messages.db`, tabla `outbound_contact_attempts`.
- Una bienvenida automática no autoriza seguimientos insistentes: esperar respuesta
  sustantiva al presupuesto. Una consulta breve por trabajo y destinatario.
- Estos límites son una política local y no garantizan evitar restricciones de WhatsApp.
