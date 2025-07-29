// frontend/src/pages/ReplayPage.tsx
import React from 'react';
import { ReplayViewer } from '../components/ReplayViewer';
import "../App.css";

export const ReplayPage: React.FC = () => {
  // ReplayViewer now handles everything including file selection and layout
  return <ReplayViewer />;
}

export default ReplayPage;