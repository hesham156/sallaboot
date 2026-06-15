import { useEffect } from 'react'

interface SEO {
  title:        string
  description?: string
  canonical?:   string
  noindex?:     boolean
  /** og:image + twitter:image. Defaults to the brand card when omitted. */
  image?:       string
  /** og:type — "website" (default) or "article" for blog posts. */
  type?:        'website' | 'article'
  /** Comma-separated keywords for the meta keywords tag. */
  keywords?:    string
}

const DEFAULT_OG_IMAGE = 'https://7ayak.app/logo.png'

/** Create-or-update a <meta> tag by name or property attribute. */
function setMeta(attr: 'name' | 'property', key: string, value: string) {
  let el = document.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`)
  if (!el) {
    el = document.createElement('meta')
    el.setAttribute(attr, key)
    document.head.appendChild(el)
  }
  el.setAttribute('content', value)
}

/**
 * Per-page SEO helper. Sets <title>, meta description + keywords, canonical,
 * the Open Graph + Twitter tags (title/description/url/image/type) and a robots
 * flag for the page that mounts it.
 *
 * The static defaults in index.html cover the landing page; this hook is what
 * every other route uses to differentiate its <title>, social preview and
 * canonical in search + when shared.
 */
export function useSEO({ title, description, canonical, noindex, image, type, keywords }: SEO) {
  useEffect(() => {
    document.title = title

    if (description) {
      setMeta('name', 'description', description)
      setMeta('property', 'og:description', description)
      setMeta('name', 'twitter:description', description)
    }
    if (keywords) {
      setMeta('name', 'keywords', keywords)
    }

    setMeta('property', 'og:title', title)
    setMeta('name', 'twitter:title', title)
    setMeta('property', 'og:type', type || 'website')

    const img = image || DEFAULT_OG_IMAGE
    setMeta('property', 'og:image', img)
    setMeta('name', 'twitter:image', img)
    setMeta('name', 'twitter:card', 'summary_large_image')

    // Canonical URL — defaults to the current path on 7ayak.app.
    const canonicalHref = canonical || `https://7ayak.app${window.location.pathname}`
    let link = document.querySelector<HTMLLinkElement>('link[rel="canonical"]')
    if (!link) {
      link = document.createElement('link')
      link.setAttribute('rel', 'canonical')
      document.head.appendChild(link)
    }
    link.setAttribute('href', canonicalHref)
    setMeta('property', 'og:url', canonicalHref)
    setMeta('name', 'twitter:url', canonicalHref)

    setMeta('name', 'robots',
      noindex ? 'noindex, nofollow' : 'index, follow, max-image-preview:large, max-snippet:-1')
  }, [title, description, canonical, noindex, image, type, keywords])
}
