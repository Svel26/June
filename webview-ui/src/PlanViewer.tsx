import React from 'react';
import { CheckCircle, Loader, Circle } from 'lucide-react';
import './App.css';

type Props = {
  plan: string[];
  currentStepIndex: number;
};

export default function PlanViewer({ plan, currentStepIndex }: Props) {
  return (
    <div className="plan-viewer">
      <ol className="plan-list">
        {plan.length === 0 ? (
          <li className="empty">No steps</li>
        ) : (
          plan.map((step, idx) => {
            const status =
              idx < currentStepIndex ? 'completed' : idx === currentStepIndex ? 'in-progress' : 'pending';
            return (
              <li key={idx} className={`plan-step ${status}`}>
                <div className="step-marker">
                  {status === 'completed' && <CheckCircle className="icon completed" />}
                  {status === 'in-progress' && <Loader className="icon spinning" />}
                  {status === 'pending' && <Circle className="icon pending" />}
                </div>
                <div className="step-content">
                  <div className="step-title">{step}</div>
                  <div className="step-meta">
                    {status === 'completed' ? 'Completed' : status === 'in-progress' ? 'In progress' : 'Pending'}
                  </div>
                </div>
              </li>
            );
          })
        )}
      </ol>
    </div>
  );
}