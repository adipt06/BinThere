export const IMAGE_LIMIT = 8 * 1024 * 1024;
export const IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
export const BIN_LABELS = { recycling: 'Recycling', compost: 'Compost', landfill: 'Regular trash', hazardous: 'Hazardous waste', ewaste: 'E-waste', donate: 'Donate or reuse', dropoff: 'Special drop-off', unknown: 'Uncertain' };
export function validateFile(file) {
  if (!file || !IMAGE_TYPES.includes(file.type)) throw new Error('Choose a JPEG, PNG or WebP image. Convert HEIC photos first.');
  if (!file.size || file.size > IMAGE_LIMIT) throw new Error('Choose a nonempty image no larger than 8 MB.');
}
export function imageDimensions(width, height) {
  if (!(width > 0 && height > 0) || width * height > 20000000) throw new Error('Use an image under 20 megapixels.');
  const scale = Math.min(1, 1024 / Math.max(width, height));
  return [Math.max(1, Math.round(width * scale)), Math.max(1, Math.round(height * scale))];
}
export function navigationAction(item) {
  // These actions browse mapped locations; material acceptance is never inferred.
  if (['recycling', 'hazardous', 'ewaste', 'dropoff'].includes(item.bin) || /batter(?:y|ies)|lithium|electronic|phone|computer|plastic (?:film|bag)/i.test(`${item.name} ${item.material}`)) return 'Recycling Location';
  if (/chemical|paint|bulb|medical|needle|aerosol/i.test(`${item.name} ${item.material}`)) return null;
  return item.bin === 'landfill' ? 'Trash Bin' : null;
}
export function validateAnalysis(data) {
  const text = (v, max) => typeof v === 'string' && v.trim().length > 0 && v.length <= max;
  const optional = (v, max) => v === null || text(v, max);
  if (!data || !text(data.summary, 600) || !optional(data.answer, 2400) || !optional(data.unsure, 1200) || !Array.isArray(data.items) || data.items.length > 8 || data.items.some(i => !i || !text(i.name, 120) || !text(i.material, 160) || !Object.hasOwn(BIN_LABELS, i.bin) || !Array.isArray(i.steps) || !i.steps.length || i.steps.length > 5 || i.steps.some(s => !text(s, 600)) || !optional(i.tip, 600))) throw new Error('The AI service returned invalid disposal guidance. Please retry.');
  return data;
}
