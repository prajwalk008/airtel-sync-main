const questions = [
  { id: 'business', text: 'Welcome to Accel Business! What kind of business do you run?', options: [{ id: 'retail', label: 'Retail shop' }, { id: 'office', label: 'Professional office' }, { id: 'food', label: 'Food business' }] },
  { id: 'team', text: 'How many people work in your business?', options: [{ id: 'small', label: '1–5 people' }, { id: 'medium', label: '6–20 people' }, { id: 'large', label: '21+ people' }] },
  { id: 'location', text: 'Which city and postcode is your business in?', options: [] },
  { id: 'problem', text: 'What would you most like to improve? You can also describe a specific problem.', options: [{ id: 'internet', label: 'Reliable internet' }, { id: 'customers', label: 'Reach customers' }, { id: 'security', label: 'Protect my business' }] },
  { id: 'budget', text: 'What monthly budget are you comfortable with?', options: [{ id: 'low', label: 'Below ₹1,000' }, { id: 'mid', label: '₹1,000–₹3,000' }, { id: 'high', label: 'Above ₹3,000' }] },
  { id: 'tools', text: 'What internet connection or digital tools do you use today?', options: [] }
];

export function validateTurn(value) {
  if (!value || typeof value !== 'object') throw new Error('Invalid advisor response');
  const { question, message, completed } = value;
  if (typeof completed !== 'boolean') throw new Error('Advisor must return completed');
  if (message !== undefined && (typeof message !== 'string' || !message.trim() || message.length > 4000)) throw new Error('Invalid advisor message');
  if (completed) {
    if (!message || question) throw new Error('Completed turn requires a message and no question');
  } else {
    if (!question || typeof question.id !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(question.id) || typeof question.text !== 'string' || !question.text.trim() || question.text.length > 1000) throw new Error('Invalid advisor question');
    if (!Array.isArray(question.options) || question.options.length > 10) throw new Error('Advisor supports up to 10 options');
    const ids = new Set();
    for (const option of question.options) {
      if (!option || typeof option.id !== 'string' || !/^[a-zA-Z0-9_-]{1,64}$/.test(option.id) || ids.has(option.id) || typeof option.label !== 'string' || !option.label.trim() || option.label.length > 20) throw new Error('Invalid advisor option');
      ids.add(option.id);
    }
  }
  return { completed, ...(message ? { message } : {}), ...(question ? { question } : {}) };
}

export function createAdvisor({ url, apiKey, fetchImpl = fetch } = {}) {
  return async (turn) => {
    if (url) {
      const response = await fetchImpl(url, {
        method: 'POST', signal: AbortSignal.timeout(45_000),
        headers: { 'Content-Type': 'application/json', ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}) },
        body: JSON.stringify(turn)
      });
      if (!response.ok) throw new Error('Advisor request failed');
      return validateTurn(await response.json());
    }
    const index = turn.answer ? questions.findIndex(q => q.id === turn.questionId) + 1 : 0;
    if (index >= questions.length) return { completed: true, message: 'Thank you! Your business details have been collected. Type /restart if you would like to start again.' };
    return validateTurn({ completed: false, question: questions[index] });
  };
}
