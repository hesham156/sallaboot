import { useEffect, useState, useRef } from 'react'
import {
  Card, CardBody, CardHeader,
  Button, Chip, Input, Spinner,
  Modal, ModalContent, ModalHeader, ModalBody, ModalFooter,
  useDisclosure, Badge, Divider, Textarea,
} from '@heroui/react'
import { api, ConvSummary, Conversation } from '../../api'

interface Props { storeId: string }

export default function Conversations({ storeId }: Props) {
  const [convs, setConvs] = useState<ConvSummary[]>([])
  const [total, setTotal] = useState(0)
  const [selected, setSelected] = useState<Conversation | null>(null)
  const [loading, setLoading] = useState(true)
  const [detailLoading, setDetailLoading] = useState(false)
  const [replyText, setReplyText] = useState('')
  const [sending, setSending] = useState(false)
  const [search, setSearch] = useState('')
  const messagesRef = useRef<HTMLDivElement>(null)

  const { isOpen, onOpen, onClose } = useDisclosure()

  useEffect(() => { loadConversations() }, [storeId])
  useEffect(() => {
    if (messagesRef.current) {
      messagesRef.current.scrollTop = messagesRef.current.scrollHeight
    }
  }, [selected?.messages])

  async function loadConversations() {
    setLoading(true)
    try {
      const res = await api.listConversations(storeId)
      setConvs(res.conversations)
      setTotal(res.total)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  }

  async function openConversation(c: ConvSummary) {
    setDetailLoading(true)
    onOpen()
    try {
      const detail = await api.getConversation(storeId, c.session_id)
      setSelected(detail)
    } catch (e) { console.error(e) }
    finally { setDetailLoading(false) }
  }

  async function sendReply() {
    if (!selected || !replyText.trim()) return
    setSending(true)
    try {
      await api.adminReply(storeId, selected.session_id, replyText.trim())
      setReplyText('')
      const updated = await api.getConversation(storeId, selected.session_id)
      setSelected(updated)
    } finally { setSending(false) }
  }

  async function handleTakeover() {
    if (!selected) return
    await api.takeover(storeId, selected.session_id)
    const updated = await api.getConversation(storeId, selected.session_id)
    setSelected(updated)
    loadConversations()
  }

  async function handleHandback() {
    if (!selected) return
    await api.handback(storeId, selected.session_id)
    const updated = await api.getConversation(storeId, selected.session_id)
    setSelected(updated)
    loadConversations()
  }

  const filtered = search
    ? convs.filter(c =>
        c.session_id.includes(search) ||
        c.last_message?.content?.toLowerCase().includes(search.toLowerCase())
      )
    : convs

  const unreadCount = convs.filter(c => c.unread).length

  return (
    <div className="p-6 space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-foreground flex items-center gap-2">
            المحادثات
            {unreadCount > 0 && (
              <Chip size="sm" color="danger">{unreadCount} جديد</Chip>
            )}
          </h1>
          <p className="text-sm text-default-400 mt-1">إجمالي: {total} محادثة</p>
        </div>
        <Button size="sm" variant="flat" onPress={loadConversations}>
          تحديث
        </Button>
      </div>

      {/* Search */}
      <Input
        placeholder="بحث في المحادثات..."
        value={search}
        onValueChange={setSearch}
        variant="bordered"
        classNames={{ inputWrapper: 'border-divider bg-content1' }}
        startContent={
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-default-400">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
        }
      />

      {/* List */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <Spinner size="lg" color="primary" />
        </div>
      ) : filtered.length === 0 ? (
        <Card className="bg-content1 border border-divider">
          <CardBody className="flex flex-col items-center justify-center py-16 gap-3">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" className="text-default-600">
              <path d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z"/>
            </svg>
            <p className="text-default-400 font-medium">لا توجد محادثات</p>
          </CardBody>
        </Card>
      ) : (
        <div className="space-y-2">
          {filtered.map(c => (
            <Card
              key={c.session_id}
              className={`bg-content1 border cursor-pointer hover:border-primary/50 transition-colors
                ${c.unread ? 'border-primary/30' : 'border-divider'}`}
              isPressable
              onPress={() => openConversation(c)}
            >
              <CardBody className="py-3 px-4">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <Chip
                        size="sm"
                        color={c.bot_enabled ? 'primary' : 'warning'}
                        variant="dot"
                      >
                        {c.bot_enabled ? 'بوت' : 'إدارة'}
                      </Chip>
                      {c.unread && <Chip size="sm" color="danger" variant="solid">جديد</Chip>}
                      {c.rating && (
                        <Chip size="sm" color="warning" variant="flat">
                          {c.rating}★
                        </Chip>
                      )}
                    </div>
                    <p className="text-sm text-default-300 truncate">
                      {c.last_message?.content
                        ? `${c.last_message.role === 'user' ? '👤' : c.last_message.role === 'admin' ? '👨‍💼' : '🤖'} ${c.last_message.content}`
                        : '—'}
                    </p>
                  </div>
                  <div className="text-left flex-shrink-0">
                    <p className="text-xs text-default-500">
                      {new Date(c.last_activity).toLocaleDateString('ar-SA')}
                    </p>
                    <p className="text-xs text-default-500 mt-0.5">
                      {c.messages_count} رسالة
                    </p>
                  </div>
                </div>
              </CardBody>
            </Card>
          ))}
        </div>
      )}

      {/* Conversation detail modal */}
      <Modal
        isOpen={isOpen}
        onClose={() => { onClose(); setSelected(null) }}
        size="3xl"
        placement="center"
        scrollBehavior="inside"
      >
        <ModalContent className="bg-content1 border border-divider max-h-[90vh]">
          {selected && (
            <>
              <ModalHeader className="flex items-center justify-between gap-3 border-b border-divider">
                <div>
                  <p className="font-bold text-sm">محادثة</p>
                  <p className="text-xs text-default-400 font-normal">{selected.session_id}</p>
                </div>
                <div className="flex gap-2">
                  {selected.bot_enabled ? (
                    <Button size="sm" color="warning" variant="flat" onPress={handleTakeover}>
                      تولي المحادثة
                    </Button>
                  ) : (
                    <Button size="sm" color="success" variant="flat" onPress={handleHandback}>
                      إعادة للبوت
                    </Button>
                  )}
                </div>
              </ModalHeader>

              <ModalBody className="p-0">
                {detailLoading ? (
                  <div className="flex items-center justify-center py-12">
                    <Spinner color="primary" />
                  </div>
                ) : (
                  <div
                    ref={messagesRef}
                    className="flex flex-col gap-3 p-4 overflow-y-auto max-h-[50vh]"
                  >
                    {selected.messages?.map((msg, i) => (
                      <div
                        key={i}
                        className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                      >
                        <div className={`
                          max-w-[80%] rounded-2xl px-4 py-2.5 text-sm
                          ${msg.role === 'user'
                            ? 'bg-primary text-white rounded-br-sm'
                            : msg.role === 'admin'
                            ? 'bg-warning/20 text-warning-foreground border border-warning/30 rounded-bl-sm'
                            : 'bg-content2 text-foreground rounded-bl-sm'
                          }
                        `}>
                          {msg.role === 'admin' && (
                            <p className="text-xs text-warning mb-1 font-semibold">الإدارة</p>
                          )}
                          <p style={{ whiteSpace: 'pre-wrap' }}>{msg.content}</p>
                          <p className={`text-xs mt-1 opacity-60`}>
                            {new Date(msg.ts).toLocaleTimeString('ar-SA', { hour: '2-digit', minute: '2-digit' })}
                          </p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </ModalBody>

              {!selected.bot_enabled && (
                <>
                  <Divider />
                  <ModalFooter className="gap-2 p-3">
                    <Textarea
                      placeholder="اكتب ردك..."
                      value={replyText}
                      onValueChange={setReplyText}
                      variant="bordered"
                      minRows={1}
                      maxRows={4}
                      className="flex-1"
                      classNames={{ inputWrapper: 'border-divider' }}
                      onKeyDown={e => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault()
                          sendReply()
                        }
                      }}
                    />
                    <Button
                      color="primary"
                      isLoading={sending}
                      isIconOnly
                      onPress={sendReply}
                      isDisabled={!replyText.trim()}
                    >
                      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
                      </svg>
                    </Button>
                  </ModalFooter>
                </>
              )}
            </>
          )}
        </ModalContent>
      </Modal>
    </div>
  )
}
