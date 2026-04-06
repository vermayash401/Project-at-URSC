/*
**  Copyright 2022 bitValence, Inc.
**  All Rights Reserved.
**
**  This program is free software; you can modify and/or redistribute it
**  under the terms of the GNU Affero General Public License
**  as published by the Free Software Foundation; version 3 with
**  attribution addendums as found in the LICENSE.txt
**
**  This program is distributed in the hope that it will be useful,
**  but WITHOUT ANY WARRANTY; without even the implied warranty of
**  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
**  GNU Affero General Public License for more details.
**
**  Purpose:
**    Implement the App C Demo application
**
**  Notes:
**    1. See header notes
**
*/

/*
** Includes
*/
#include <stdio.h>
#include <string.h>
#include <time.h>
#include <errno.h>
#include "app_c_demo_app.h"
#include "app_c_demo_eds_cc.h"
#include "telemetry_compressor.h"
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>
/***********************/
/** Macro Definitions **/
/***********************/

/* Convenience macros */
#define  INITBL_OBJ    (&(AppCDemo.IniTbl))
#define  CMDMGR_OBJ    (&(AppCDemo.CmdMgr))
#define  TBLMGR_OBJ    (&(AppCDemo.TblMgr))
#define  CHILDMGR_OBJ  (&(AppCDemo.ChildMgr))
#define TX_CHUNK_SIZE  120
#define UDP_MAGIC      0x43534653u
#define  DEVICE_OBJ        (&(AppCDemo.Device))
#define  HISTOGRAM_OBJ     (&(AppCDemo.Histogram))
#define  HISTOGRAM_LOG_OBJ (&(AppCDemo.Histogram.Log))

typedef struct
{
   uint32 Magic;
   uint16 BatchId;
   uint16 ChunkOffset;
   uint16 TotalSize;
   uint16 ChunkSize;
   uint8  Data[TX_CHUNK_SIZE];
} UdpChunkPacket_t;

/*******************************/
/** Local Function Prototypes **/
/*******************************/

static int32 InitApp(void);
static int32 ProcessCommands(void);
static void SendStatusTlm(void);
static int SendAll(const uint8 *buf, size_t len);
static int udp_sock = -1;
static struct sockaddr_in ground_addr;
static UdpChunkPacket_t udp_packet;

/**********************/
/** File Global Data **/
/**********************/

/* 
** Must match DECLARE ENUM() declaration in app_cfg.h
** Defines "static INILIB_CfgEnum_t IniCfgEnum"
*/
DEFINE_ENUM(Config,APP_CONFIG)  


static CFE_EVS_BinFilter_t  EventFilters[] =
{

   /* Event ID                Mask                  */
   {DEVICE_RANDOM_DATA_EID,   CFE_EVS_FIRST_8_STOP}
   
};


/*****************/
/** Global Data **/
/*****************/

APP_C_DEMO_Class_t  AppCDemo;
static uint8_t comp_buf[MAX_COMPRESSED_SIZE];
static uint8_t queued_comp_buf[MAX_COMPRESSED_SIZE];
static uint16_t size=0;
static uint16_t last_size = 0;
static uint16_t tx_index = 0;
static uint16_t queued_size = 0;
static uint16_t active_batch_id = 0;
static uint16_t queued_batch_id = 0;
static uint16_t next_batch_id = 0;
static time_t next_frame_time = 0;

static int SendAll(const uint8 *buf, size_t len)
{
   size_t sent = 0;

   while (sent < len)
   {
      ssize_t rc = send(udp_sock, buf + sent, len - sent, 0);

      if (rc <= 0)
      {
         return -1;
      }

      sent += (size_t)rc;
   }

   return 0;
}

/******************************************************************************
** Function: APP_C_DEMO_AppMain
**
*/
void APP_C_DEMO_AppMain(void)
{

   uint32 RunStatus = CFE_ES_RunStatus_APP_ERROR;
   
   CFE_EVS_Register(EventFilters,sizeof(EventFilters)/sizeof(CFE_EVS_BinFilter_t),
                    CFE_EVS_EventFilter_BINARY);

   if (InitApp() == CFE_SUCCESS)      /* Performs initial CFE_ES_PerfLogEntry() call */
   {
      RunStatus = CFE_ES_RunStatus_APP_RUN; 
   }

   /*
   ** At this point flight apps may use CFE_ES_WaitForStartupSync()
   ** to synchronize their startup timing with other apps.
   */
   
   /*
   ** Main process loop
   */
   while (CFE_ES_RunLoop(&RunStatus))
   {
      
      RunStatus = ProcessCommands();  /* Pends indefinitely & manages CFE_ES_PerfLogEntry() calls */
      
   } /* End CFE_ES_RunLoop */

   CFE_ES_WriteToSysLog("APP_C_DEMO App terminating, run status = 0x%08X\n", RunStatus);   /* Use SysLog, events may not be working */

   CFE_EVS_SendEvent(APP_C_DEMO_EXIT_EID, CFE_EVS_EventType_CRITICAL, "APP_C_DEMO App terminating, run status = 0x%08X", RunStatus);

   CFE_ES_ExitApp(RunStatus);  /* Let cFE kill the task (and any child tasks) */

} /* End of APP_C_DEMO_AppMain() */


/******************************************************************************
** Function: APP_C_DEMO_NoOpCmd
**
*/
bool APP_C_DEMO_NoOpCmd(void *ObjDataPtr, const CFE_MSG_Message_t *MsgPtr)
{

   uint32 PipeIndex;

   CFE_EVS_SendEvent (APP_C_DEMO_NOOP_EID, CFE_EVS_EventType_INFORMATION,
                      "No operation command received for APP_C_DEMO App version %d.%d.%d",
                      APP_C_DEMO_MAJOR_VER, APP_C_DEMO_MINOR_VER, APP_C_DEMO_PLATFORM_REV);


   CFE_SB_PipeId_ToIndex(AppCDemo.CmdPipe, &PipeIndex);
   CFE_EVS_SendEvent (APP_C_DEMO_NOOP_EID, CFE_EVS_EventType_DEBUG,
                      "AppCDemo.CmdPipe = %d",PipeIndex);

   return true;


} /* End APP_C_DEMO_NoOpCmd() */


/******************************************************************************
** Function: APP_C_DEMO_ResetAppCmd
**
** Notes:
**   1. Framework objects require an object reference since they are
**      reentrant. Applications use the singleton pattern and store a
**      reference pointer to the object data during construction.
*/
bool APP_C_DEMO_ResetAppCmd(void *ObjDataPtr, const CFE_MSG_Message_t *MsgPtr)
{

   CMDMGR_ResetStatus(CMDMGR_OBJ);
   TBLMGR_ResetStatus(TBLMGR_OBJ);
   CHILDMGR_ResetStatus(CHILDMGR_OBJ);
   
   DEVICE_ResetStatus();
   HISTOGRAM_ResetStatus();
	  
   return true;

} /* End APP_C_DEMO_ResetAppCmd() */


/******************************************************************************
** Function: InitApp
**
*/
static int32 InitApp(void)
{

   int32 RetStatus = APP_C_FW_CFS_ERROR;
   
   CHILDMGR_TaskInit_t ChildTaskInit;
   
   /*
   ** Read JSON INI Table & Initialize Child Manager  
   */
   
   if (INITBL_Constructor(INITBL_OBJ, APP_C_DEMO_INI_FILENAME, &IniCfgEnum))
   {
   
      AppCDemo.PerfId  = INITBL_GetIntConfig(INITBL_OBJ, CFG_APP_PERF_ID);
      CFE_ES_PerfLogEntry(AppCDemo.PerfId);

      AppCDemo.CmdMid     = CFE_SB_ValueToMsgId(INITBL_GetIntConfig(INITBL_OBJ, CFG_APP_C_DEMO_CMD_TOPICID));
      AppCDemo.ExecuteMid = CFE_SB_ValueToMsgId(INITBL_GetIntConfig(INITBL_OBJ, CFG_APP_C_DEMO_EXE_TOPICID));

      /* Child Manager constructor sends error events */
      ChildTaskInit.TaskName  = INITBL_GetStrConfig(INITBL_OBJ, CFG_CHILD_NAME);
      ChildTaskInit.StackSize = INITBL_GetIntConfig(INITBL_OBJ, CFG_CHILD_STACK_SIZE);
      ChildTaskInit.Priority  = INITBL_GetIntConfig(INITBL_OBJ, CFG_CHILD_PRIORITY);
      ChildTaskInit.PerfId    = INITBL_GetIntConfig(INITBL_OBJ, CHILD_PERF_ID);

      RetStatus = CHILDMGR_Constructor(CHILDMGR_OBJ, 
                                       ChildMgr_TaskMainCmdDispatch,
                                       NULL, 
                                       &ChildTaskInit); 
  
   } /* End if INITBL Constructed */
  
   if (RetStatus == CFE_SUCCESS)
   {

      /* Must constructor table manager prior to any app objects that contain tables */
      TBLMGR_Constructor(TBLMGR_OBJ, INITBL_GetStrConfig(INITBL_OBJ, CFG_APP_CFE_NAME));

      /*
      ** Constuct app's contained objects
      */
           
      DEVICE_Constructor(DEVICE_OBJ, INITBL_GetIntConfig(INITBL_OBJ, CFG_DEVICE_DATA_MODULO));
      HISTOGRAM_Constructor(HISTOGRAM_OBJ, INITBL_OBJ, TBLMGR_OBJ);
      
      /*
      ** Initialize app level interfaces
      */
      
      CFE_SB_CreatePipe(&AppCDemo.CmdPipe, INITBL_GetIntConfig(INITBL_OBJ, CFG_APP_CMD_PIPE_DEPTH), INITBL_GetStrConfig(INITBL_OBJ, CFG_APP_CMD_PIPE_NAME));  
      CFE_SB_Subscribe(AppCDemo.CmdMid,     AppCDemo.CmdPipe);
      CFE_SB_Subscribe(AppCDemo.ExecuteMid, AppCDemo.CmdPipe);

      CMDMGR_Constructor(CMDMGR_OBJ);
      CMDMGR_RegisterFunc(CMDMGR_OBJ, APP_C_DEMO_NOOP_CC,  NULL, APP_C_DEMO_NoOpCmd,     0);
      CMDMGR_RegisterFunc(CMDMGR_OBJ, APP_C_DEMO_RESET_CC, NULL, APP_C_DEMO_ResetAppCmd, 0);
      
      CMDMGR_RegisterFunc(CMDMGR_OBJ, APP_C_DEMO_LOAD_TBL_CC, TBLMGR_OBJ, TBLMGR_LoadTblCmd, sizeof(APP_C_DEMO_LoadTbl_CmdPayload_t));
      CMDMGR_RegisterFunc(CMDMGR_OBJ, APP_C_DEMO_DUMP_TBL_CC, TBLMGR_OBJ, TBLMGR_DumpTblCmd, sizeof(APP_C_DEMO_DumpTbl_CmdPayload_t));

      CMDMGR_RegisterFunc(CMDMGR_OBJ, APP_C_DEMO_START_HISTOGRAM_CC, HISTOGRAM_OBJ, HISTOGRAM_StartCmd, 0);
      CMDMGR_RegisterFunc(CMDMGR_OBJ, APP_C_DEMO_STOP_HISTOGRAM_CC,  HISTOGRAM_OBJ, HISTOGRAM_StopCmd,  0);

      /*
      ** The following commands are executed within the context of a child task. See the App Dev Guide for details.
      */
      
      CMDMGR_RegisterFunc(CMDMGR_OBJ, APP_C_DEMO_START_HISTOGRAM_LOG_CC,        CHILDMGR_OBJ, CHILDMGR_InvokeChildCmd, sizeof(APP_C_DEMO_StartHistogramLog_CmdPayload_t));
      CMDMGR_RegisterFunc(CMDMGR_OBJ, APP_C_DEMO_STOP_HISTOGRAM_LOG_CC,         CHILDMGR_OBJ, CHILDMGR_InvokeChildCmd, 0);
      CMDMGR_RegisterFunc(CMDMGR_OBJ, APP_C_DEMO_START_HISTOGRAM_LOG_PLAYBK_CC, CHILDMGR_OBJ, CHILDMGR_InvokeChildCmd, 0);
      CMDMGR_RegisterFunc(CMDMGR_OBJ, APP_C_DEMO_STOP_HISTOGRAM_LOG_PLAYBK_CC,  CHILDMGR_OBJ, CHILDMGR_InvokeChildCmd, 0);
      CHILDMGR_RegisterFunc(CHILDMGR_OBJ, APP_C_DEMO_START_HISTOGRAM_LOG_CC,        HISTOGRAM_LOG_OBJ, HISTOGRAM_LOG_StartLogCmd);
      CHILDMGR_RegisterFunc(CHILDMGR_OBJ, APP_C_DEMO_STOP_HISTOGRAM_LOG_CC,         HISTOGRAM_LOG_OBJ, HISTOGRAM_LOG_StopLogCmd);
      CHILDMGR_RegisterFunc(CHILDMGR_OBJ, APP_C_DEMO_START_HISTOGRAM_LOG_PLAYBK_CC, HISTOGRAM_LOG_OBJ, HISTOGRAM_LOG_StartPlaybkCmd);
      CHILDMGR_RegisterFunc(CHILDMGR_OBJ, APP_C_DEMO_STOP_HISTOGRAM_LOG_PLAYBK_CC,  HISTOGRAM_LOG_OBJ, HISTOGRAM_LOG_StopPlaybkCmd);

      /* 
      ** Alternative commands don't increment the main command counters, but they do increment the child command counters.
      ** This "command" is used by the app's main loop to perform periodic processing 
      */
      CMDMGR_RegisterFuncAltCnt(CMDMGR_OBJ, APP_C_DEMO_RUN_HISTOGRAM_LOG_CHILD_TASK_CC, CHILDMGR_OBJ,      CHILDMGR_InvokeChildCmd, sizeof(APP_C_DEMO_RunHistogramLogChildTask_CmdPayload_t));
      CHILDMGR_RegisterFunc(CHILDMGR_OBJ,   APP_C_DEMO_RUN_HISTOGRAM_LOG_CHILD_TASK_CC, HISTOGRAM_LOG_OBJ, HISTOGRAM_LOG_RunChildTaskCmd);


      /*
      ** Initialize app messages 
      */


      CFE_MSG_Init(CFE_MSG_PTR(AppCDemo.RunHistogramLogChildTask.CommandBase), AppCDemo.CmdMid, sizeof(APP_C_DEMO_RunHistogramLogChildTask_t));
      CFE_MSG_SetFcnCode(CFE_MSG_PTR(AppCDemo.RunHistogramLogChildTask.CommandBase), (CFE_MSG_FcnCode_t)APP_C_DEMO_RUN_HISTOGRAM_LOG_CHILD_TASK_CC);

      CFE_MSG_Init(CFE_MSG_PTR(AppCDemo.StatusTlm.TelemetryHeader), 
                   CFE_SB_ValueToMsgId(INITBL_GetIntConfig(INITBL_OBJ, CFG_APP_C_DEMO_STATUS_TLM_TOPICID)),
                   sizeof(APP_C_DEMO_StatusTlm_t));

      /*
      ** Application startup event message
      */
      CFE_EVS_SendEvent(APP_C_DEMO_INIT_APP_EID, CFE_EVS_EventType_INFORMATION,
                        "APP_C_DEMO App Initialized. Version %d.%d.%d",
                        APP_C_DEMO_MAJOR_VER, APP_C_DEMO_MINOR_VER, APP_C_DEMO_PLATFORM_REV);

   } /* End if CHILDMGR constructed */
   udp_sock = socket(AF_INET, SOCK_STREAM, 0);

   memset(&ground_addr, 0, sizeof(ground_addr));
   ground_addr.sin_family = AF_INET;
   ground_addr.sin_port = htons(6000);
   ground_addr.sin_addr.s_addr = inet_addr("10.171.39.71");

   if (udp_sock >= 0)
   {
      if (connect(udp_sock, (struct sockaddr *)&ground_addr, sizeof(ground_addr)) != 0)
      {
         CFE_EVS_SendEvent(999, CFE_EVS_EventType_ERROR,
                           "TCP connect failed: %s", strerror(errno));
      }
      else
      {
         CFE_EVS_SendEvent(995, CFE_EVS_EventType_INFORMATION,
                           "TCP connected to %s:%u",
                           "10.171.39.71", 6000);
      }
   }
   return RetStatus;

} /* End of InitApp() */


/******************************************************************************
** Function: ProcessCommands
**
** 
*/
static int32 ProcessCommands(void)
{
   
   int32  RetStatus = CFE_ES_RunStatus_APP_RUN;
   int32  SysStatus;
   uint16 BinNum;
   uint16 DataSample;
   uint16 GeneratedSize = 0;
   uint16 FramesToGenerate = 0;
   CFE_SB_Buffer_t *SbBufPtr;
   CFE_SB_MsgId_t   MsgId = CFE_SB_INVALID_MSG_ID;
   time_t Now;


   CFE_ES_PerfLogExit(AppCDemo.PerfId);
   SysStatus = CFE_SB_ReceiveBuffer(&SbBufPtr, AppCDemo.CmdPipe, CFE_SB_PEND_FOREVER);
   CFE_ES_PerfLogEntry(AppCDemo.PerfId);

   if (SysStatus == CFE_SUCCESS)
   {
      SysStatus = CFE_MSG_GetMsgId(&SbBufPtr->Msg, &MsgId);

      if (SysStatus == CFE_SUCCESS)
      {

         if (CFE_SB_MsgId_Equal(MsgId, AppCDemo.CmdMid))
         {
            CMDMGR_DispatchFunc(CMDMGR_OBJ, &SbBufPtr->Msg);
         } 
         else if (CFE_SB_MsgId_Equal(MsgId, AppCDemo.ExecuteMid))
         {

            DataSample = DEVICE_ReadData();
       

            if (HISTOGRAM_AddDataSample(DataSample, &BinNum))
            {

               AppCDemo.RunHistogramLogChildTask.Payload.BinNum     = BinNum;
               AppCDemo.RunHistogramLogChildTask.Payload.DataSample = DataSample;
               CFE_MSG_GenerateChecksum(CFE_MSG_PTR(AppCDemo.RunHistogramLogChildTask.CommandBase));
               CMDMGR_DispatchFunc(CMDMGR_OBJ, CFE_MSG_PTR(AppCDemo.RunHistogramLogChildTask.CommandBase));
            }

            Now = time(NULL);

            if (next_frame_time == 0)
               next_frame_time = Now;

            while (Now >= next_frame_time)
            {
               FramesToGenerate += 2;
               next_frame_time++;
            }

            if (queued_size == 0)
            {
               uint8_t *target_buf = (size == 0) ? comp_buf : queued_comp_buf;
               uint16_t target_capacity = (size == 0) ? sizeof(comp_buf) : sizeof(queued_comp_buf);
               int gen_status = telemetry_generate_and_compress(FramesToGenerate,
                                                                target_buf,
                                                                target_capacity,
                                                                &GeneratedSize);

               if (gen_status < 0)
               {
                  CFE_EVS_SendEvent(998, CFE_EVS_EventType_ERROR,
                                    "Compression failed (frames=%u, capacity=%u)",
                                    FramesToGenerate, target_capacity);
               }
               else if (gen_status == 1)
               {
                  if (size == 0)
                  {
                     size = GeneratedSize;
                     tx_index = 0;
                     last_size = size;
                     active_batch_id = next_batch_id++;
                  }
                  else
                  {
                     queued_size = GeneratedSize;
                     queued_batch_id = next_batch_id++;
                  }
               }
            }

            


 memset(&udp_packet, 0, sizeof(udp_packet));

 uint16 remaining = size - tx_index;
uint16 chunk = (remaining >= TX_CHUNK_SIZE) ? TX_CHUNK_SIZE : remaining;

if (size > 0 && chunk > 0)
{
    uint16 chunk_offset = tx_index;

    memcpy((uint8 *)&AppCDemo.StatusTlm.Payload.DeviceData,
           &comp_buf[tx_index],
           chunk);

    udp_packet.Magic = UDP_MAGIC;
    udp_packet.BatchId = active_batch_id;
    udp_packet.ChunkOffset = chunk_offset;
    udp_packet.TotalSize = size;
    udp_packet.ChunkSize = chunk;
    memcpy(udp_packet.Data, &comp_buf[tx_index], chunk);

    AppCDemo.StatusTlm.Payload.ChunkSize = chunk;
    tx_index += chunk;
}
else
{
    // No active data
    AppCDemo.StatusTlm.Payload.ChunkSize = 0;

    if (queued_size > 0)
    {
        memcpy(comp_buf, queued_comp_buf, queued_size);
        size = queued_size;
        last_size = size;
        queued_size = 0;
        active_batch_id = queued_batch_id;
        queued_batch_id = 0;
        tx_index = 0;
    }
    else
    {
        size = 0;
        tx_index = 0;
    }
}
SendStatusTlm();
if (udp_packet.ChunkSize > 0)
{
   if (SendAll((const uint8 *)&udp_packet, sizeof(udp_packet)) != 0)
   {
      CFE_EVS_SendEvent(994, CFE_EVS_EventType_ERROR,
                        "TCP send failed: %s", strerror(errno));
   }
}
CFE_EVS_SendEvent(996, CFE_EVS_EventType_INFORMATION,
                  "CORTEX-SAT TX COMPRESSED - Sending idx=%u / %u, chunk=%u",
                  tx_index, last_size, chunk);          
         }
         else
         {   
            CFE_EVS_SendEvent(APP_C_DEMO_INVALID_MID_EID, CFE_EVS_EventType_ERROR,
                              "Received invalid command packet, MID = 0x%04X", 
                             CFE_SB_MsgIdToValue(MsgId));
         }

      } /* End if got message ID */
   } /* End if received buffer */
   else
   {
      RetStatus = CFE_ES_RunStatus_APP_ERROR;
   } 

   return RetStatus;
   
} /* End ProcessCommands() */


/******************************************************************************
** Function: SendStatusTlm
**
*/
static void SendStatusTlm(void)
{

   /* Good design practice in case app expands to more than one table */
   const TBLMGR_Tbl_t *LastTbl = TBLMGR_GetLastTblStatus(TBLMGR_OBJ);

   APP_C_DEMO_StatusTlm_Payload_t *Payload = &AppCDemo.StatusTlm.Payload;
   
   /*
   ** Framework Data
   */
   
   Payload->ValidCmdCnt   = AppCDemo.CmdMgr.ValidCmdCnt;
   Payload->InvalidCmdCnt = AppCDemo.CmdMgr.InvalidCmdCnt;
   
   Payload->ChildValidCmdCnt   = AppCDemo.ChildMgr.ValidCmdCnt;
   Payload->ChildInvalidCmdCnt = AppCDemo.ChildMgr.InvalidCmdCnt;
   
   /*
   ** Table Data 
   ** - Loaded with status from the last table action 
   */

   Payload->LastTblAction       = LastTbl->LastAction;
   Payload->LastTblActionStatus = LastTbl->LastActionStatus;
          }
