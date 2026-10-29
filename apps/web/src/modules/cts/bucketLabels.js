// Review-bucket names, taken from the message taxonomy so every screen says the same thing.
import { msg } from '../../shared/messages'

export const INWARD_BUCKETS = ['HVC', 'CA', 'IP', 'LVC', 'FCC', 'SIP_SUCCESS', 'SIP_REJECT', 'HR', 'MISC']

export function bucketLabel(code) {
  const key = `CTS_WF_BUCKET_${code}`
  const text = msg(key)
  return text === key ? code : text            // an unknown bucket shows its code
}

// The short form used inside a row's reason text: "mismatch", "miscellaneous".
export function bucketShort(code) {
  const key = `CTS_OUT_Q_BUCKET_${code}`
  const text = msg(key)
  return text === key ? bucketLabel(code) : text
}
