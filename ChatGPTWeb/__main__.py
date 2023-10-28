# from ChatGPTWeb.ChatGPTWeb import chatgpt
# from ChatGPTWeb.config import MsgData,Personality
# import asyncio
# import aioconsole

from ChatGPTWeb import chatgpt
from config import MsgData,Personality
import asyncio
import aioconsole

session_token=[
    "eyJhbGciOiJkaXIiLCJlbmMiOiJBMjU2R0NNIn0..shn9lHTUk0BvPQFN.-ad9K5t0qzWGjunE55RZGCvo_vnDJSLAmerKYUsI5I5hUgVxHYVYSA-s2zdsLyDX2Wh-nAUjF1Oes42KFoiopNay4jukGwQrzU7wU2m1dbSFyL1nQCGN5hY1Pp8LEK-JKM_xKMsFW9Zi6x0hj7X9NCnqzTCbdDuFT7crJOsS4GRFvBQxMoLLzO3fV1kyzN9bZNBwH-Lxof_9nqVRHKIFcGtsPk0IgEcg2EmjGLU3f1tT0NGJlVFi2Rwfz85v1eMcxDV9j6F8qp_T1SCWmmX9japLThwX-bRCrOq6wbzhtRbLpYPNJ3iMUT0yzRI7AdVgfdxBcOseHktYL6GqCRv_0rOaiscH9eIKqF82MYsvGzHfarh_JusGbvhqNnfb3_Lgg_UivhBjH1qwX5A66_pK8GPG4V36b3QEXFoLD4Fda8gbARNaLZkeNoDUgYtGyWyoLk_X8unCMIuqh9CueKto6yoK-IFlGEDSVb6fxjQylVLFNTbrZqPPej73fauBia1yZW9xdiStaBiRYz7u30q90LaZIusujyH951HtDk7v3vqSsCkf0oONX3AEdULlCGzJKnq6uZtaaUOfKjud0tM5iFNzOiFqJ8FqOcDo55x2z1u7JI1qZQLVNNLRTetNUCjbk_cuFy_N_X2kf9MEA9fpiJSGaFG3M517BWT0oXG8FEP13FHELb6nOQdQO7qWFi73y7-G06sBcJ_GkX8lG1F7Dtl7Ci6mEj5wTiHnPCmtSK16OFCV5oigzRQmFc2TXphQSDo1BXP7ABVQc0HsgOw-npI9YCXOa-m2rDoW9XM4-vzy_PWXKHjX7mR6PQGGPg2AHCUWxGWna93sww26kxYW9BOmPZF6CH0TwmH1UtRBPLOf8Ty6B-gLIGzpBWKP2m7eFMDQjvNWiSUX-0uKFelIRspKeNFjjXlqyw1d2rXL4xAV0Cc7thYt2sW0x0kWBoG9Z-tb6F6ojQS_7lohAW0CdOo2fihp9kPX1LaTnHpvcNIlz-apnLTfQtD380v6HA_bQd2GqErTojY_XBugUePwDsWrAykeUKQNHGBC3rN-MVWcxxrZu2B4qjWXvnRvzvsji9jo--AgDdfpglmCfdHI0d0fDyVj56R1grkZhBjHzcyCIEmXgeQWte5B18l20-iCY9wTIKD3tB77yL2DVXXK2VXfJW96898AEv4vG0CCGwf28h7WUg_aDTxis6IUvK1s5qedJAjtgIrM-u9XP-b_CgzHmvi4XvBHI6KEAuVs4OO9xBFBGPA8nBt3wpsYcjqip8l45q0uzRsB-BeVsO7d-fSXHkS8gP9aYbBOxZH0GE2oYzRuv23TiRVfCF5lAeO6AkmNDINZtzhSNlNhfh87_14g2E2POH1AWAsoYzMGUIrfeFtl79m_JZCKYSkqaMurfl9wtRdYAc2x3L3v2vdxTKKtbP7u-0cIiGk10Cebv4e8SUXaBBATwaYwSdo5d_XV80sEg3LokBHp42VsN1OUYgZkst2ylTzNguFUUknQPLYb3Mb4xaAyeZAEGLmEbEd4qizNVRR9aoOFaZWlsQOav3PgAflREFMkcIkHRpLjftWZSN_fxxyPZHWangtdTBUUb4n50ezHGbp_6VuZ4NofK7DSWxBTSp7Jn62s7gPaWXpZCzvFWBz7dzh408sV9L6w8QayljtmjltH85ICi8RQBcilg5-Z1q1KAaYTs5RMZyETGgDGp3sX3Pg_KcXl-dbmPmQ9aDTFpjc_iM1WOxSBqFgSRjQCsLULy4GNIm8C0rl4a2BvK8zmT5QO1-P5T0EOsHGyJubLsbbxBu-teB-kQ8AKuzzNC3InI_Fyeg2kXZmkLf-pb2Qnp-rQrQ7JiszLnCONqAwSKCXNCDk0kh4cXm6aTp6GHlDuMK3LMQlNj4lVywYu6y9gTiQAYgKfsT0PeemHZH_s8kB0nvtRpC9ealSzMDeDiROVST0JOYb1ur5l_b0K5bArozVRBG8ROF2wjkfmMC6PaI9hSo4_SRrIHE6j7eeCJDMYEx-DaK3Nzzl6nhUDCPANUfvY4SfBKSAn1xESct_8nOFD5SvjS_Q7yFApNimvgymqku0DVChs6IgB9UUBAgzLLRHpl1jdbUEur0OG6wS0c7Q5p_CQq3CBlLUV3OxweIFliA6squYa8K7pZX7Xa90NUTO-sO2gA6n3s0P5kg0MmLwD-reBaAU5LbhPt9sfCEAn2q3bdklXDhIRhqYagLGGDchwJlftBp-0qP1NmYGQQSuBGvn2yV5uvTi3X09lpuORi9-Vbrn8j4HNN7zo3P0zJhGIEe8MHrw8wmpYNTfrKc2yejiA7wjhOWOdUKoLfEkpAVawBxQqVCKxOHxA_6IWo7hddySEFleVKd1E2JrrwzQGKoEAjY1yAwrpd6GXY3lxQwq_sHymRb6Qwvrgg2KxAAHrxl3freYatZ2D_PHivpue43yT3q0xGnTfrK5WhMFXr8_hMK-rzrq7pny4pLtrqB332JOIOgj36AXKkvxfOG8QIGdDnIOfGXNUDgqlPqFA2kFZPZay-4Rw0M16QY6hlMvTmQxM7iMNUDVORmS9teP4HXg1XxNFD8KHeg_fpE2nqs3lyjErYGgGMS8xEDFC61KJMmPOJYIcUBCy4mD3UpvcSIh0hOK7VKGtYmWLtM-NJ2Ehl3lkuSmD6JXC4YOvp3yHnYnvOO4Z4dTaY3UBUiKqLCjmjtx_7vg6jwJr69P5tRlOi_LFC7fvFAuTx7lk3m_khCC_RNvlCvQ0QEsSuW_0ySFEoU_my2wn0gdS-FXP3GhZcjmfIAupAHJeTc-36h-ZH3HLL_kCUGv_LYloGSYtvJ1_4ErLAZjSSY8PnjlqTRxB3JBZrEHaXUSE4wiqKMVVzXAES5GjTOPsBnQ4cUvvQBjZ2GPPE4yCfbETKqwb.IQqiioR9lH7PshLBkHwfVQ"
]

personality_definition = Personality(
    [
        {
            "name":"one",
            'value':'one value'
            },
        {
            "name":"two",
            "value":'two value'
        }
        ])

proxy = {
    "http":"http://127.0.0.1:1090",
    "https":"https://127.0.0.1:1090"
}
proxy = {"server": "http://127.0.0.1:1090"}
chat = chatgpt(session_token=session_token,proxy=proxy)
#,log_status=False
async def main():
    
    c_id = await aioconsole.ainput("your conversation_id if you have:")
    p_id = await aioconsole.ainput("your parent_message_id if you have:")
    data:MsgData = MsgData(conversation_id=c_id,p_msg_id=p_id)
    while 1:
        print("\n------------------------------")
        data.msg_send = await aioconsole.ainput("input：")
        print("------------------------------\n")
        if data.msg_send == "quit":
            break
        elif data.msg_send == "re":
            data.msg_type = "back_loop"
            data.p_msg_id = await aioconsole.ainput("your parent_message_id if you go back:")
        elif data.msg_send == "reset":
            data = await chat.back_init_personality(data)
            print(f"ChatGPT:{data.msg_recv}")
            continue
        elif data.msg_send == "init_personality":
            data.msg_send = "your ..."
            data = await chat.init_personality(data)
            print(f"ChatGPT:{data.msg_recv}")
            continue
        elif data.msg_send == "history":
            print(await chat.show_chat_history(data))
            continue
        data = await chat.continue_chat(data)
        print(f"ChatGPT:{data.msg_recv}")
        
        
loop = asyncio.get_event_loop()
loop.run_until_complete(main())           
    