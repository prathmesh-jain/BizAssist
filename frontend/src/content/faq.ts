/** Landing-page FAQ. Also emitted as FAQPage structured data by the prerender step, so keep answers factual. */
export const FAQS: { q: string; a: string }[] = [
    {
        q: 'What is BizAssist?',
        a: 'BizAssist is an AI assistant for small businesses. It learns how your business works, then answers questions from your own documents, reads and updates Google Sheets, manages Google Calendar and Meet, and researches your competitors, all from one chat.',
    },
    {
        q: 'How does BizAssist learn about my business?',
        a: 'You answer a few questions about your business. BizAssist then researches public information such as your website, listings and competitors, and shows you a draft profile with sources. Each fact is labelled verified, estimated or not found, and only the version you confirm is used.',
    },
    {
        q: 'Which tools does BizAssist work with?',
        a: 'Today it works with Google Sheets, Google Calendar and Google Meet, plus documents you upload (PDF, Word and plain text). You can also attach PDFs, images and text files directly in a chat.',
    },
    {
        q: 'Will it change my calendar without asking?',
        a: 'No. Creating, moving or cancelling a calendar event always shows you exactly what will happen and waits for your approval.',
    },
    {
        q: 'Can my whole team use it?',
        a: 'Yes. Invite people as owners, admins, members or viewers. The business profile and documents are shared across your organization, while each person’s chats and calendar stay private to them.',
    },
    {
        q: 'Which AI models does BizAssist use?',
        a: 'You bring your own API key from OpenAI, Anthropic (Claude), Google Gemini, OpenRouter or any OpenAI-compatible server, and choose the models in Settings. Usage is billed directly to your provider account. Document search uses OpenAI embeddings, so it needs an OpenAI key.',
    },
];
