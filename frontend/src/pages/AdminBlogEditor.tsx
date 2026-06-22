import { useEffect, useRef, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import { api, BlogPostInput } from '../api'

marked.setOptions({ async: false, gfm: true, breaks: false })

function renderMarkdown(md: string): string {
  const rawHtml = marked.parse(md || '') as string
  return DOMPurify.sanitize(rawHtml, {
    USE_PROFILES: { html: true },
    ADD_ATTR: ['target', 'rel'],
  })
}

/** title → "my-post-title-2026" (lowercase, hyphens, ascii only). */
function slugify(input: string): string {
  return input
    .toLowerCase()
    .trim()
    // Strip Arabic + non-ASCII → empty (slug stays ascii for clean URLs).
    .replace(/[^\x00-\x7F]+/g, '')
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 80)
}

const EMPTY: BlogPostInput = {
  slug:        '',
  title:       '',
  description: '',
  content_md:  '',
  tags:        [],
  author:      'فريق حياك',
  read_time:   5,
  published:   false,
  cover_image: '',
}

export default function AdminBlogEditor() {
  const navigate = useNavigate()
  const params   = useParams<{ id: string }>()
  const isEdit   = params.id !== 'new' && !!params.id
  const postId   = isEdit ? Number(params.id) : null

  const [form, setForm]       = useState<BlogPostInput>(EMPTY)
  const [tagsInput, setTagsInput] = useState('')
  const [loading, setLoading] = useState(isEdit)
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')
  const [message, setMessage] = useState('')
  // user manually edited the slug → stop auto-deriving from title
  const [slugTouched, setSlugTouched] = useState(isEdit)
  const [uploadingCover,  setUploadingCover]  = useState(false)
  const [uploadingInline, setUploadingInline] = useState(false)
  const contentRef = useRef<HTMLTextAreaElement | null>(null)

  async function uploadCover(file: File) {
    setUploadingCover(true); setError('')
    try {
      const { url } = await api.blogUploadImage(file)
      update('cover_image', url)
    } catch (e: any) {
      setError(e.message || 'تعذّر رفع صورة الغلاف')
    } finally { setUploadingCover(false) }
  }

  async function uploadInline(file: File) {
    setUploadingInline(true); setError('')
    try {
      const { url } = await api.blogUploadImage(file)
      const md = `\n\n![${file.name.replace(/\.[^.]+$/, '')}](${url})\n\n`
      // Insert at the cursor when possible, else append.
      const ta = contentRef.current
      if (ta) {
        const start = ta.selectionStart ?? form.content_md.length
        const next = form.content_md.slice(0, start) + md + form.content_md.slice(start)
        update('content_md', next)
      } else {
        update('content_md', form.content_md + md)
      }
    } catch (e: any) {
      setError(e.message || 'تعذّر رفع الصورة')
    } finally { setUploadingInline(false) }
  }

  useEffect(() => {
    document.title = isEdit ? 'تعديل مقال | حياك' : 'مقال جديد | حياك'
    if (!isEdit || !postId) return
    api.blogGetAdmin(postId)
      .then(p => {
        setForm({
          slug:        p.slug,
          title:       p.title,
          description: p.description,
          content_md:  p.content_md,
          tags:        p.tags,
          author:      p.author,
          read_time:   p.read_time,
          published:   p.published,
          cover_image: p.cover_image || '',
        })
        setTagsInput(p.tags.join(', '))
      })
      .catch(e => setError(e.message || 'تعذّر تحميل المقال'))
      .finally(() => setLoading(false))
  }, [isEdit, postId])

  function update<K extends keyof BlogPostInput>(key: K, value: BlogPostInput[K]) {
    setForm(f => ({ ...f, [key]: value }))
    setMessage('')
  }

  function onTitleChange(value: string) {
    update('title', value)
    if (!slugTouched) {
      const derived = slugify(value)
      if (derived) setForm(f => ({ ...f, slug: derived }))
    }
  }

  function onTagsChange(value: string) {
    setTagsInput(value)
    const arr = value.split(',').map(t => t.trim()).filter(Boolean)
    update('tags', arr)
  }

  async function onSave(publishNow?: boolean) {
    setError('')
    setMessage('')
    if (!form.title.trim()) { setError('العنوان مطلوب'); return }
    if (!form.slug.trim())  { setError('الـ slug مطلوب'); return }

    const payload: BlogPostInput = {
      ...form,
      published: publishNow !== undefined ? publishNow : form.published,
    }
    setSaving(true)
    try {
      if (isEdit && postId) {
        const updated = await api.blogUpdate(postId, payload)
        setForm(f => ({ ...f, published: updated.published }))
        setMessage(updated.published ? '✅ تم النشر' : '✅ تم حفظ المسودة')
      } else {
        const created = await api.blogCreate(payload)
        setMessage('✅ تم إنشاء المقال')
        // Re-route to the edit page so the URL reflects the real id.
        navigate(`/admin/blog/${created.id}`, { replace: true })
      }
    } catch (e: any) {
      setError(e.message || 'فشل الحفظ')
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div dir="rtl" className="min-h-screen flex items-center justify-center text-slate-400">
        جاري التحميل…
      </div>
    )
  }

  return (
    <div dir="rtl" className="min-h-screen bg-slate-50 font-sans">
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3 min-w-0">
            <button
              onClick={() => navigate('/admin/blog')}
              className="text-slate-500 hover:text-slate-900 flex-shrink-0"
              title="رجوع للقائمة"
            >
              <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                <path d="M5 12h14M12 5l7 7-7 7" />
              </svg>
            </button>
            <h1 className="text-base sm:text-lg font-bold text-slate-900 truncate">
              {isEdit ? form.title || 'تعديل مقال' : 'مقال جديد'}
            </h1>
            {form.published && (
              <span className="hidden sm:inline-flex items-center gap-1.5 text-xs font-bold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2.5 py-1 rounded-full flex-shrink-0">
                <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full" />
                منشور
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 flex-shrink-0">
            <button
              onClick={() => onSave(false)}
              disabled={saving}
              className="text-sm font-bold text-slate-700 bg-white border border-slate-200 rounded-full px-4 py-2 hover:border-slate-400 disabled:opacity-50"
            >
              {saving ? '…' : 'حفظ كمسودة'}
            </button>
            <button
              onClick={() => onSave(true)}
              disabled={saving}
              className="text-sm font-bold text-white bg-teal-600 hover:bg-teal-700 rounded-full px-5 py-2 disabled:opacity-50"
            >
              {saving ? 'جاري…' : form.published ? 'حفظ التعديلات' : 'نشر'}
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6">
        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">{error}</div>
        )}
        {message && (
          <div className="mb-4 p-3 bg-emerald-50 border border-emerald-200 rounded-xl text-emerald-700 text-sm">{message}</div>
        )}

        {/* Metadata grid */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
          <div className="lg:col-span-2 space-y-4">
            <div>
              <label className="block text-xs font-bold text-slate-600 mb-1.5">العنوان <span className="text-red-500">*</span></label>
              <input
                type="text"
                value={form.title}
                onChange={e => onTitleChange(e.target.value)}
                placeholder="مثال: كيف تبني متجر إلكتروني ناجح في ٧ أيام"
                className="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-base font-bold focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
              />
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-600 mb-1.5">
                الـ Slug (الرابط) <span className="text-red-500">*</span>
                <span className="text-slate-400 font-normal mr-2">— حروف صغيرة + شرطات فقط</span>
              </label>
              <div className="flex items-center gap-0 border border-slate-200 rounded-xl overflow-hidden focus-within:ring-2 focus-within:ring-teal-500">
                <span className="bg-slate-100 px-3 py-2.5 text-sm text-slate-500 font-mono border-l border-slate-200 dir-ltr">/blog/</span>
                <input
                  type="text"
                  value={form.slug}
                  onChange={e => { update('slug', slugify(e.target.value) || e.target.value); setSlugTouched(true) }}
                  placeholder="my-first-post"
                  className="flex-1 px-3 py-2.5 text-sm font-mono dir-ltr focus:outline-none"
                />
              </div>
            </div>

            <div>
              <label className="block text-xs font-bold text-slate-600 mb-1.5">
                الوصف (Meta Description)
                <span className="text-slate-400 font-normal mr-2">— يظهر في نتايج Google ({form.description.length}/160)</span>
              </label>
              <textarea
                value={form.description}
                onChange={e => update('description', e.target.value)}
                rows={2}
                placeholder="اكتب وصف مختصر يحفّز القارئ على الضغط على نتيجة البحث"
                className="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent resize-none"
              />
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <label className="block text-xs font-bold text-slate-600 mb-1.5">الكاتب</label>
              <input
                type="text"
                value={form.author}
                onChange={e => update('author', e.target.value)}
                className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-slate-600 mb-1.5">وقت القراءة (دقايق)</label>
              <input
                type="number"
                min={1}
                max={60}
                value={form.read_time}
                onChange={e => update('read_time', Number(e.target.value) || 5)}
                className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
              />
            </div>
            <div>
              <label className="block text-xs font-bold text-slate-600 mb-1.5">
                الوسوم (مفصولة بفواصل)
              </label>
              <input
                type="text"
                value={tagsInput}
                onChange={e => onTagsChange(e.target.value)}
                placeholder="بوت سلة, واتساب أعمال, دليل تعليمي"
                className="w-full px-3 py-2 border border-slate-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent"
              />
              {form.tags.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {form.tags.map(t => (
                    <span key={t} className="text-xs font-bold text-teal-700 bg-teal-50 border border-teal-100 px-2 py-0.5 rounded-full">
                      {t}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Cover image */}
        <div className="bg-white border border-slate-200 rounded-2xl p-5">
          <label className="block text-xs font-bold text-slate-600 mb-2">
            صورة الغلاف
            <span className="text-slate-400 font-normal mr-2">— تُحسَّن تلقائيًا (WebP، بحد أقصى 1600px)</span>
          </label>
          {form.cover_image ? (
            <div className="flex items-start gap-4 flex-wrap">
              <img src={form.cover_image} alt="غلاف المقال" loading="lazy"
                className="w-56 aspect-video object-cover rounded-xl border border-slate-200 bg-slate-50" />
              <div className="flex flex-col gap-2">
                <label className={`inline-flex items-center justify-center gap-1.5 text-xs font-bold rounded-lg px-3 py-2 cursor-pointer transition-colors ${
                  uploadingCover ? 'opacity-60 pointer-events-none' : 'text-teal-700 bg-teal-50 hover:bg-teal-100'
                }`}>
                  {uploadingCover ? 'جاري الرفع…' : 'تغيير الصورة'}
                  <input type="file" accept="image/*" className="hidden"
                    onChange={e => { const f = e.target.files?.[0]; if (f) uploadCover(f); e.target.value = '' }} />
                </label>
                <button type="button" onClick={() => update('cover_image', '')}
                  className="text-xs font-bold text-red-600 bg-red-50 hover:bg-red-100 rounded-lg px-3 py-2 transition-colors">
                  إزالة
                </button>
              </div>
            </div>
          ) : (
            <label className={`flex flex-col items-center justify-center gap-2 w-full py-10 border-2 border-dashed border-slate-200 rounded-xl cursor-pointer hover:border-teal-300 hover:bg-teal-50/40 transition-colors ${
              uploadingCover ? 'opacity-60 pointer-events-none' : ''
            }`}>
              <svg width={28} height={28} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.8}
                strokeLinecap="round" strokeLinejoin="round" className="text-slate-400">
                <rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" />
              </svg>
              <span className="text-sm font-bold text-slate-500">
                {uploadingCover ? 'جاري الرفع…' : 'اضغط لرفع صورة الغلاف'}
              </span>
              <span className="text-xs text-slate-400">PNG / JPG / WebP</span>
              <input type="file" accept="image/*" className="hidden"
                onChange={e => { const f = e.target.files?.[0]; if (f) uploadCover(f); e.target.value = '' }} />
            </label>
          )}
        </div>

        {/* Markdown editor + preview */}
        <div className="bg-white border border-slate-200 rounded-2xl overflow-hidden">
          <div className="grid grid-cols-1 lg:grid-cols-2">
            <div className="border-l border-slate-200">
              <div className="px-4 py-2 bg-slate-50 border-b border-slate-200 text-xs font-bold text-slate-600 flex items-center justify-between">
                <span>المحتوى (Markdown)</span>
                <label className={`inline-flex items-center gap-1.5 text-xs font-bold rounded-lg px-2.5 py-1 cursor-pointer transition-colors ${
                  uploadingInline ? 'opacity-60 pointer-events-none' : 'text-teal-700 bg-teal-50 hover:bg-teal-100'
                }`}>
                  <svg width={13} height={13} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="3" width="18" height="18" rx="2" /><circle cx="8.5" cy="8.5" r="1.5" /><path d="M21 15l-5-5L5 21" />
                  </svg>
                  {uploadingInline ? 'جاري الرفع…' : 'إدراج صورة'}
                  <input type="file" accept="image/*" className="hidden"
                    onChange={e => { const f = e.target.files?.[0]; if (f) uploadInline(f); e.target.value = '' }} />
                </label>
              </div>
              <textarea
                ref={contentRef}
                value={form.content_md}
                onChange={e => update('content_md', e.target.value)}
                placeholder={`# مقدمة\n\nاكتب مقالك هنا بتنسيق Markdown:\n\n## عنوان فرعي\n\n**نص عريض** أو *مائل*\n\n- نقطة أولى\n- نقطة ثانية\n\n[رابط](https://example.com)\n\n> اقتباس مهم`}
                className="w-full min-h-[500px] lg:min-h-[700px] p-5 font-mono text-sm leading-relaxed focus:outline-none resize-y"
                dir="auto"
              />
            </div>
            <div>
              <div className="px-4 py-2 bg-slate-50 border-b border-slate-200 text-xs font-bold text-slate-600 flex items-center justify-between">
                <span>المعاينة</span>
                <span className="text-slate-400 font-normal">{form.content_md.length} حرف</span>
              </div>
              <PreviewStyles />
              <div
                className="article-body p-5 min-h-[500px] lg:min-h-[700px] overflow-y-auto"
                dir="rtl"
                dangerouslySetInnerHTML={{ __html: renderMarkdown(form.content_md) }}
              />
            </div>
          </div>
        </div>

        {/* Markdown quick reference */}
        <details className="mt-6 bg-white border border-slate-200 rounded-xl">
          <summary className="cursor-pointer p-4 text-sm font-bold text-slate-700 hover:bg-slate-50">
            دليل سريع لـ Markdown
          </summary>
          <div className="px-4 pb-4 text-sm text-slate-600 space-y-2 leading-loose">
            <div><code className="bg-slate-100 px-1.5 py-0.5 rounded">## عنوان</code> — عنوان رئيسي</div>
            <div><code className="bg-slate-100 px-1.5 py-0.5 rounded">### عنوان فرعي</code> — عنوان فرعي</div>
            <div><code className="bg-slate-100 px-1.5 py-0.5 rounded">**نص عريض**</code> — نص <strong>عريض</strong></div>
            <div><code className="bg-slate-100 px-1.5 py-0.5 rounded">*نص مائل*</code> — نص <em>مائل</em></div>
            <div><code className="bg-slate-100 px-1.5 py-0.5 rounded">[نص الرابط](https://...)</code> — رابط</div>
            <div><code className="bg-slate-100 px-1.5 py-0.5 rounded">- نقطة</code> — قائمة نقطية</div>
            <div><code className="bg-slate-100 px-1.5 py-0.5 rounded">1. نقطة</code> — قائمة مرقّمة</div>
            <div><code className="bg-slate-100 px-1.5 py-0.5 rounded">{`> اقتباس`}</code> — اقتباس</div>
            <div><code className="bg-slate-100 px-1.5 py-0.5 rounded">![وصف](image.jpg)</code> — صورة</div>
          </div>
        </details>
      </main>
    </div>
  )
}

function PreviewStyles() {
  return (
    <style>{`
      .article-body { color: #334155; font-size: 1rem; line-height: 1.9; }
      .article-body > *:first-child { margin-top: 0; }
      .article-body p { margin: .9rem 0; }
      .article-body h1 { font-size: 1.8rem; font-weight: 900; color: #0f172a; margin-top: 1.5rem; margin-bottom: .8rem; }
      .article-body h2 { font-size: 1.5rem; font-weight: 900; color: #0f172a; margin-top: 2rem; margin-bottom: .8rem; }
      .article-body h3 { font-size: 1.2rem; font-weight: 800; color: #0f172a; margin-top: 1.5rem; margin-bottom: .6rem; }
      .article-body strong { color: #0f172a; font-weight: 700; }
      .article-body a { color: #0d9488; font-weight: 700; text-decoration: none; border-bottom: 1px dashed #5eead4; }
      .article-body ul, .article-body ol { margin: .8rem 0; padding-right: 1.5rem; }
      .article-body li { margin: .3rem 0; }
      .article-body ul li { list-style: disc; }
      .article-body ol li { list-style: decimal; }
      .article-body code { color: #0f766e; background: #ccfbf1; padding: 1px 6px; border-radius: 4px; font-size: .9em; direction: ltr; display: inline-block; }
      .article-body blockquote { margin: 1rem 0; padding: .8rem 1rem; background: #f0fdfa; border-right: 4px solid #14b8a6; border-radius: 6px; color: #134e4a; }
      .article-body blockquote p { margin: 0; }
      .article-body hr { margin: 1.5rem 0; border: none; border-top: 1px solid #e2e8f0; }
      .article-body img { max-width: 100%; border-radius: 8px; }
    `}</style>
  )
}
