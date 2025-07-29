// frontend/src/pages/ReplayPage.tsx
import React from 'react';
import { BoardReplay } from '../components/BoardReplay';
import "../App.css";

export const ReplayPage: React.FC = () => {
  // ReplayViewer now handles everything including file selection and layout
  return <BoardReplay />;
}

export default ReplayPage;