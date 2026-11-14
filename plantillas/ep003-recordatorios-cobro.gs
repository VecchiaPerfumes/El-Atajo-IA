/**
 * El Atajo IA · Recordatorios de cobro automáticos (episodio 3)
 *
 * Hoja "Cobros" con columnas, en este orden (fila 1 = encabezados):
 * A Cliente | B Correo | C Concepto | D Monto | E Vencimiento (fecha) | F Estado (pendiente/pagado) | G Último aviso
 *
 * Uso: Extensiones > Apps Script > pega este código > guarda > ejecuta "enviarRecordatorios" una vez
 * para dar permisos > Activadores > agregar: enviarRecordatorios, basado en tiempo, diario, 9 a 10 am.
 */
const NEGOCIO = 'Tu negocio';
const FORMA_PAGO = 'Transferencia a la cuenta 0000 0000 0000 0000 (Banco X).';

const MENSAJES = {
  antes: 'Hola {cliente}, te recuerdo que el pago de {monto} por {concepto} vence el {fecha}. {pago} ¡Gracias!',
  hoy: 'Hola {cliente}, hoy vence el pago de {monto} por {concepto}. {pago} Si ya pagaste, ignora este mensaje.',
  despues: 'Hola {cliente}, ¿todo bien? El pago de {monto} por {concepto} venció el {fecha}. Si necesitas otra fecha, respóndeme y lo vemos. {pago}',
};

function enviarRecordatorios() {
  const dia = new Date().getDay();
  if (dia === 0 || dia === 6) return; // nunca en fin de semana

  const hoja = SpreadsheetApp.getActive().getSheetByName('Cobros');
  const filas = hoja.getDataRange().getValues();
  const hoy = new Date(); hoy.setHours(0, 0, 0, 0);
  const tz = Session.getScriptTimeZone();

  for (let i = 1; i < filas.length; i++) {
    const [cliente, correo, concepto, monto, venc, estado, ultimo] = filas[i];
    if (!correo || String(estado).toLowerCase() !== 'pendiente' || !(venc instanceof Date)) continue;
    const v = new Date(venc); v.setHours(0, 0, 0, 0);
    const dias = Math.round((v - hoy) / 86400000); // positivo = faltan días

    let tipo = null;
    if (dias === 3) tipo = 'antes';
    else if (dias === 0) tipo = 'hoy';
    else if (dias === -3) tipo = 'despues';
    if (!tipo) continue;

    const hoyTxt = Utilities.formatDate(hoy, tz, 'yyyy-MM-dd');
    if (ultimo && Utilities.formatDate(new Date(ultimo), tz, 'yyyy-MM-dd') === hoyTxt) continue;

    const cuerpo = MENSAJES[tipo]
      .replace('{cliente}', cliente)
      .replace('{monto}', '$' + Number(monto).toLocaleString('es-MX'))
      .replace('{concepto}', concepto)
      .replace('{fecha}', Utilities.formatDate(v, tz, 'dd/MM/yyyy'))
      .replace('{pago}', FORMA_PAGO);

    MailApp.sendEmail(correo, `${NEGOCIO}: recordatorio de pago`, cuerpo);
    hoja.getRange(i + 1, 7).setValue(new Date());
  }
}
