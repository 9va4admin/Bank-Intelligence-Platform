/**
 * Real cheque scan images served from demo/112/ via Vite dev middleware.
 * URL format: /demo-cheques/<filename>
 *
 * Usage:
 *   import { demoChequeUrl } from '../demoImages'
 *   front_bw_url: demoChequeUrl(index)   // wraps around if index > 111
 */

const FILENAMES = [
  'Cheque 083654.jpeg','Cheque 083655.jpeg','Cheque 083656.jpeg',
  'Cheque 083657.jpeg','Cheque 083658.jpeg','Cheque 083659.jpeg',
  'Cheque 083660.jpeg',
  'Cheque 100828.jpeg','Cheque 100829.jpeg','Cheque 100830.jpeg',
  'Cheque 100831.jpeg','Cheque 100832.jpeg','Cheque 100833.jpeg',
  'Cheque 100834.jpeg','Cheque 100835.jpeg',
  'Cheque 120611.jpeg','Cheque 120612.jpeg','Cheque 120613.jpeg',
  'Cheque 120614.jpeg','Cheque 120615.jpeg','Cheque 120616.jpeg',
  'Cheque 120617.jpeg','Cheque 120618.jpeg','Cheque 120619.jpeg',
  'Cheque 120620.jpeg',
  'Cheque 309061.jpeg','Cheque 309062.jpeg','Cheque 309063.jpeg',
  'Cheque 309066.jpeg','Cheque 309067.jpeg','Cheque 309068.jpeg',
  'Cheque 309069.jpeg','Cheque 309070.jpeg','Cheque 309071.jpeg',
  'Cheque 309072.jpeg','Cheque 309073.jpeg','Cheque 309074.jpeg',
  'Cheque 309075.jpeg','Cheque 309076.jpeg','Cheque 309077.jpeg',
  'Cheque 309078.jpeg','Cheque 309079.jpeg','Cheque 309080.jpeg',
  'Cheque 309082.jpeg','Cheque 309083.jpeg','Cheque 309084.jpeg',
  'Cheque 309086.jpeg','Cheque 309089.jpeg','Cheque 309090.jpeg',
  'Cheque 309091.jpeg','Cheque 309092.jpeg','Cheque 309093.jpeg',
  'Cheque 309094.jpeg','Cheque 309095.jpeg','Cheque 309096.jpeg',
  'Cheque 309097.jpeg','Cheque 309098.jpeg','Cheque 309099.jpeg',
  'Cheque 309100.jpeg','Cheque 309101.jpeg','Cheque 309102.jpeg',
  'Cheque 309103.jpeg','Cheque 309104.jpeg','Cheque 309105.jpeg',
  'Cheque 309106.jpeg','Cheque 309107.jpeg','Cheque 309108.jpeg',
  'Cheque 309109.jpeg','Cheque 309110.jpeg','Cheque 309111.jpeg',
  'Cheque 309112.jpeg','Cheque 309113.jpeg','Cheque 309114.jpeg',
  'Cheque 309115.jpeg','Cheque 309116.jpeg','Cheque 309117.jpeg',
  'Cheque 309118.jpeg','Cheque 309119.jpeg','Cheque 309121.jpeg',
  'Cheque 309122.jpeg','Cheque 309123.jpeg','Cheque 309124.jpeg',
  'Cheque 309125.jpeg','Cheque 309126.jpeg','Cheque 309127.jpeg',
  'Cheque 309128.jpeg','Cheque 309129.jpeg','Cheque 309130.jpeg',
  'Cheque 309131.jpeg','Cheque 309133.jpeg','Cheque 309134.jpeg',
  'Cheque 309135.jpeg','Cheque 309136.jpeg','Cheque 309137.jpeg',
  'Cheque 309138.jpeg','Cheque 309139.jpeg','Cheque 309141.jpeg',
  'Cheque 309142.jpeg','Cheque 309144.jpeg','Cheque 309145.jpeg',
  'Cheque 309147.jpeg','Cheque 309148.jpeg','Cheque 309149.jpeg',
  'Cheque 309150.jpeg','Cheque 309151.jpeg','Cheque 309153.jpeg',
  'Cheque 309155.jpeg','Cheque 309156.jpeg','Cheque 309157.jpeg',
  'Cheque 309158.jpeg','Cheque 309159.jpeg','Cheque 309160.jpeg',
]

export const DEMO_CHEQUE_COUNT = FILENAMES.length  // 112

/**
 * Returns a `/demo-cheques/<name>` URL for the given index.
 * Wraps modulo 112 so any index works.
 */
export function demoChequeUrl(index) {
  const name = FILENAMES[Math.abs(index) % FILENAMES.length]
  return `/demo-cheques/${encodeURIComponent(name)}`
}

/**
 * Returns all 112 URLs — useful for carousel / gallery views.
 */
export const ALL_DEMO_URLS = FILENAMES.map(
  name => `/demo-cheques/${encodeURIComponent(name)}`
)
