#include "time.h"

/*
定时器中断实现过程:
1、勾选定时器驱动 --> 在标准外围设备确定中查找
2、RCC定时器硬件时钟使能
3、TIM_TimeBaseInit定时器基本参数的初始化 --> stm32f10x_tim.c
4、NVIC_Init初始化 --> misc.c
5、TIM_Cmd启动定时器工作 --> stm32f10x_tim.c
6、TIM_ITConfig使能定时器中断 --> stm32f10x_tim.c
7、书写中断响应函数
(1)中断响应函数返回值都是void
(2)中断响应函数的形参列表都是 void
(3)中断响应函数的函数名 -->startup_stm32f10x_hd.s
TIM1_UP_IRQHandler、TIM2_IRQHandler、 TIM3_IRQHandler
TIM4_IRQHandler、TIM5_IRQHandler、TIM6_IRQHandler
TIM7_IROHandler、TIM8_UP_IRQHandler
(4)在中断响应函数中进行判断，判断中断是否被触发
	if (TIM_GetITStatus (TIM_TypeDef* TIMx, uintl6 t TIM IT) != RESET)
	{
		//实现灯的亮灭操作
		//清楚中断状态标志位
		TIM_ClearITPendingBit (TIM_TypeDef* TIMx, uintl6_ t  TIM_IT) ;
	}
8、按照上述操作步骤，使用定时器1，定时500毫秒LED灯亮灭操作
*/

void time1_init(uint16_t arr, uint16_t psc)	//	TIM_ARR寄存器（自动重载寄存器）、psc（Prescaler的缩写）
{
	TIM_TimeBaseInitTypeDef TIM_TimeBaseInitStruct;
	
	// 1.打开外设时钟  TIM1--APB2
	RCC_APB2PeriphClockCmd(RCC_APB2Periph_TIM1, ENABLE);
	
	// TIM_Period是定时周期，相当于是设置定时时长的参数
	// 如果要设置定时周期，就需要先知道定时器的频率
	// 想要知道定时器的频率，就先得知道其原始频率
	// 原始频率需要看当前定时器从属于哪个设备总线
	// 然后在结合时钟体系，并进行两次分频操作，得到定时器的最终频率
	// APB (72MHz) / TIM Prescaler (7200)/ TIM ClockDivision (1) = 10000Hz
	// 定时器最终频率为10000Hz(系统计数10000次需要花费1s)
	
	// APB2定时时钟   定时500ms   72MHZ（72000000HZ）数72000000次花费1s   数72000000*0.5次花费500ms
	//				  定时500ms   经过7200分频   10KHZ（10000HZ）数10000次花费1s   数5000次花费500ms
	
	// 配置定时器TIM1的参数
	TIM_TimeBaseInitStruct.TIM_Period = arr-1;	// 计数周期（打算数多少次）：5000
	TIM_TimeBaseInitStruct.TIM_Prescaler = psc -1;	// 预分频值（数数的快慢）：7200
	TIM_TimeBaseInitStruct.TIM_CounterMode = TIM_CounterMode_Up;	// 计数模式（打算怎么数）：递增计数
	TIM_TimeBaseInitStruct.TIM_ClockDivision = TIM_CKD_DIV1;	// 第二次分频系数
	
	// 定时器1初始化
	TIM_TimeBaseInit(TIM1, &TIM_TimeBaseInitStruct);

	
	// 配置NVIC全局中断（中断通道+优先级）
	NVIC_InitTypeDef NVIC_InitStruct;
	NVIC_InitStruct.NVIC_IRQChannel = TIM1_UP_IRQn;	// 配置中断通道
	NVIC_InitStruct.NVIC_IRQChannelPreemptionPriority = 0x0F;	// 抢占优先级
	NVIC_InitStruct.NVIC_IRQChannelSubPriority = 0x0F;	// 响应优先级
	NVIC_InitStruct.NVIC_IRQChannelCmd = ENABLE;	// 使能中断通道
	
	// 初始化NVIC
	NVIC_Init(&NVIC_InitStruct);
	
	
	// 使能定时器1工作
	TIM_Cmd(TIM1, ENABLE);
	
	
	// 使能TIM1的中断源，更新事件发生中断
	TIM_ITConfig(TIM1, TIM_IT_Update, ENABLE);
}

// TIM1的中断服务函数
void TIM1_UP_IRQHandler(void)
{
	if(TIM_GetITStatus (TIM1, TIM_IT_Update) != RESET)	// RESET = 0, SET = !RESET
	{
		// 实现灯的亮灭操作
		PAout(8) ^= 1;	// 电平反转
		
		// 清除中断状态标志位
		// 防止程序被卡死 -- 如果不清除中断标志位，程序会一直申请中断，程序会不断响应中断，执行中断函数
		TIM_ClearITPendingBit (TIM1, TIM_IT_Update);
	}	
}
