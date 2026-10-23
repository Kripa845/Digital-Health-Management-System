// Methods some libraries use that older phones lack (Safari before 15.4). Imported first in main.tsx.

function at<T>(this: ArrayLike<T>, index: number): T | undefined {
  const n = Math.trunc(index) || 0
  const i = n < 0 ? this.length + n : n
  return i >= 0 && i < this.length ? this[i] : undefined
}

for (const proto of [Array.prototype, String.prototype] as object[]) {
  if (!('at' in proto)) {
    Object.defineProperty(proto, 'at', { value: at, writable: true, configurable: true })
  }
}

export {}
