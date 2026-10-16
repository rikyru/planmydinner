// Data locale in formato YYYY-MM-DD. toISOString() usa UTC: in Italia tra
// mezzanotte e le 2 restituirebbe il giorno prima (e il lunedì sbagliato).
export function localISO(d = new Date()) {
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
